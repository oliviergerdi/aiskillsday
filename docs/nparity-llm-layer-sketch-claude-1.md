# nParity: swappable LLM layer (initial shape)

Design sketch, not build code. Ruby, on the assumption that one language end to end (your strongest) is fastest. The same shape ports to anything else.

Hold off committing any of this to the repo before 09:15 Thursday.

Updated after `logprobs_report.md` (Fireworks, DeepSeek V4.1 Flash): the logprob approach works. Changes from the first draft are marked `REPORT`.

## Shape

```
mapper / triage  ──►  Evaluator (Jev-shaped interface)
                          │
                 ┌────────┼──────────┬──────────────┐
                 ▼        ▼          ▼              ▼
             Cached   FlashLogprob   Jev        Fake (answer key)
          (decorator)  (work)      (home)      (tests, offline demo)
```

- Callers only ever see `evaluate(state:, questions:) -> { id => Answer }`.
- Every backend reports `capabilities` so callers can adapt: shortlist to `max_options`, skip `reason` when it isn't supported.
- `backend_id` (backend + model version) goes into cache keys and threshold lookups.

## Types

```ruby
module NParity
  module LLM
    Noul   = Data.define(:id, :instructions, :criteria)          # criteria: { true:, false: } or nil
    Choice = Data.define(:id, :instructions, :criteria)          # criteria: { key => description }
    Score  = Data.define(:id, :instructions, :criteria)          # criteria: [level0, level1, ...]

    Answer = Data.define(
      :value,          # Choice: key; Noul: probability of yes; Score: weighted mean level
      :probabilities,  # { key/level/true|false => p }, sums to 1
      :confidence,     # 0..1, from the distribution's shape
      :reason,         # String or nil (only when the backend gives reasons)
      :censored        # REPORT: true when some options fell outside top_logprobs (k > 5 on Flash)
    )

    Capabilities = Data.define(
      :calibrated,         # true for Jev, false for Flash
      :max_options,        # Jev 255; Flash 30 for ranking (REPORT: E8 still picks right at 30)
      :calibrated_options, # REPORT: Flash 5 (top_logprobs hard max); Jev 255
      :gives_reasons,
      :batches_questions   # Jev: all questions in one call; Flash: one call per question
    )
  end
end
```

## The interface

```ruby
module NParity::LLM
  class Backend
    def backend_id   = raise NotImplementedError   # e.g. "flash:deepseek-v4p1-flash-1017-us"
    def capabilities = raise NotImplementedError

    # state: Hash or String; questions: Array of Noul/Choice/Score
    # returns { question_id => Answer }
    def evaluate(state:, questions:, reasons: false) = raise NotImplementedError
  end

  def self.build(env = ENV)
    backend =
      case env.fetch("NPARITY_LLM", "flash")
      when "flash" then FlashLogprob.new(
                          # REPORT: only the -us router is callable on our account (others 403 on region)
                          model: env.fetch("FLASH_MODEL", "accounts/fireworks/routers/deepseek-v4p1-flash-1017-us"),
                          api_key: env.fetch("FIREWORKS_API_KEY"))
      when "jev"   then Jev.new(model: env.fetch("JEV_MODEL", "jev-latest"), api_key: env.fetch("TYPESAFE_API_KEY"))
      when "fake"  then Fake.new(answer_key: env.fetch("ANSWER_KEY_PATH"))
      end
    Cached.new(backend, store: FileStore.new("tmp/llm_cache"))
  end
end
```

## Shared helpers

```ruby
module NParity::LLM::Distribution
  module_function

  # logprobs: { "A" => -0.1, "B" => -2.3, ... } restricted to our option codes
  # REPORT: top_logprobs caps at 5, so missing codes are "below the cutoff", not zero.
  # Give each missing code the floor (the 5th-ranked logprob) before normalising.
  # Returns [probs, censored?]
  def softmax(logprobs, codes, floor:)
    present = logprobs.slice(*codes)
    return [codes.to_h { |c| [c, 1.0 / codes.size] }, true] if present.empty? # off-list answer
    filled = codes.to_h { |c| [c, present.fetch(c, floor)] }
    max = filled.values.max
    exps = filled.transform_values { |l| Math.exp(l - max) }
    total = exps.values.sum
    [exps.transform_values { |v| v / total }, present.size < codes.size]
  end

  # 1 - normalised entropy: 1.0 when one option dominates, 0.0 when uniform
  def confidence(probs)
    n = probs.size
    return 1.0 if n <= 1
    h = -probs.values.sum { |p| p.zero? ? 0 : p * Math.log(p) }
    1.0 - h / Math.log(n)
  end
end
```

## Flash adapter (logprob trick)

Assumptions to confirm from the Fireworks logprobs report are marked `CONFIRM`.

```ruby
require "net/http"
require "json"

class NParity::LLM::FlashLogprob < NParity::LLM::Backend
  URL   = URI("https://us.api.fireworks.ai/inference/v1/chat/completions")  # REPORT: us. host
  # REPORT (E4, E13): "A" and "01".."30" come back as bare single tokens in chat mode.
  LETTERS = ("A".."Z").to_a
  DIGITS  = (1..30).map { |i| format("%02d", i) }

  # REPORT (E6): no position bias, so permutations stay at 1 by default.
  def initialize(model:, api_key:, top_logprobs: 5, permutations: 1)
    @model, @api_key, @top, @perms = model, api_key, top_logprobs, permutations
  end

  def backend_id   = "flash:#{@model.split('/').last}"
  def capabilities = NParity::LLM::Capabilities.new(calibrated: false, max_options: DIGITS.size,
                                                    calibrated_options: 5,
                                                    gives_reasons: true, batches_questions: false)

  def evaluate(state:, questions:, reasons: false)
    questions.to_h { |q| [q.id, answer(state, q, reasons)] }  # parallelise with threads if slow
  end

  private

  def answer(state, q, reasons)
    options = options_for(q)                 # [[key, description], ...]
    raise ArgumentError, "too many options" if options.size > DIGITS.size
    # REPORT (E12): near-duplicate options tie exactly. Dedupe candidates before calling this.
    # REPORT (E15): never re-ask a trimmed shortlist; ask once with the full list.

    runs = Array.new(@perms) { |i| i.zero? ? options : options.shuffle(random: Random.new(i)) }
    results = runs.map { |opts| one_run(state, q, opts) }
    probs = results.map(&:first)
                   .reduce { |acc, p| acc.merge(p) { |_, a, b| a + b } }
                   .transform_values { |v| v / runs.size }

    NParity::LLM::Answer.new(
      value: value_for(q, probs),
      probabilities: probs,
      confidence: NParity::LLM::Distribution.confidence(probs),
      reason: reasons ? explain(state, q, probs) : nil,
      censored: results.any?(&:last)
    )
  end

  def one_run(state, q, opts)
    codes = opts.size <= LETTERS.size ? LETTERS.first(opts.size) : DIGITS.first(opts.size)
    body = {
      model: @model,
      reasoning_effort: "none",    # REPORT (E3): mandatory; "minimal"/"low" still reason
      temperature: 0,
      max_tokens: 1,               # REPORT: finish_reason is "length"; don't gate on "stop"
      logprobs: true,
      top_logprobs: @top,          # REPORT (E2): hard max 5
      messages: [
        { role: "system", content: "Answer with only the code of the best option. No other text." },
        { role: "user", content: prompt(state, q, opts, codes) }  # state first => prefix caching
      ]
    }
    lp = first_token_logprobs(post(body))
    floor = lp.values.min || -20.0
    by_code, censored = NParity::LLM::Distribution.softmax(lp, codes, floor: floor)
    [codes.zip(opts).to_h { |code, (key, _)| [key, by_code[code]] }, censored]
  end

  def prompt(state, q, opts, codes)
    <<~P
      #{state.is_a?(String) ? state : JSON.pretty_generate(state)}

      #{q.instructions}
      #{codes.zip(opts).map { |c, (_, desc)| "#{c}: #{desc}" }.join("\n")}
    P
  end

  def options_for(q)
    case q
    when NParity::LLM::Choice then q.criteria.to_a
    when NParity::LLM::Score  then q.criteria.each_with_index.map { |desc, i| [i, desc] }
    # REPORT (E5): "is X the same as Y?" reads as strict identity and says N to a correct
    # rename match. For mapping, ask a Choice and derive yes/no from p(best) vs p(none).
    # Noul is still fine for triage questions that really are yes/no.
    when NParity::LLM::Noul   then [[true, q.criteria&.dig(:true) || "Yes"], [false, q.criteria&.dig(:false) || "No"]]
    end
  end

  def value_for(q, probs)
    case q
    when NParity::LLM::Choice then probs.max_by { |_, p| p }.first
    when NParity::LLM::Score  then probs.sum { |level, p| level * p }
    when NParity::LLM::Noul   then probs[true]
    end
  end

  # REPORT (E1): chat returns OpenAI shape, choices[0].logprobs.content[0].top_logprobs.
  # Stay on chat: /completions returns " A" with a leading space and different probabilities.
  def first_token_logprobs(resp)
    lp = resp.dig("choices", 0, "logprobs")
    raw =
      if lp&.key?("content")
        lp.dig("content", 0, "top_logprobs").to_h { |t| [t["token"], t["logprob"]] }
      else
        lp&.dig("top_logprobs", 0) || {}
      end
    # Normalise " A", "A.", "A\n" -> "A"; keep the best logprob per code
    raw.each_with_object({}) do |(tok, l), acc|
      code = tok.strip.delete_suffix(".").delete_suffix(":")
      acc[code] = [acc[code], l].compact.max
    end
  end

  # Reasons cost a second call; only request them for items the report will show.
  # REPORT (E9): alternative is one JSON-mode call {"label","reason"} with the label logprob
  # at token index 3. ~35 output tokens instead of 1, and its probabilities are
  # grammar-conditioned, so keep the label from the plain call and use JSON only for the reason.
  def explain(state, q, probs)
    winner = probs.max_by { |_, p| p }.first
    # Normal chat call, reasoning_effort "none", max_tokens ~60:
    # "In one sentence, why is <winner> the answer?"  Left as a stub for now.
  end

  def post(body)
    req = Net::HTTP::Post.new(URL, "Authorization" => "Bearer #{@api_key}", "Content-Type" => "application/json")
    req.body = body.to_json
    res = Net::HTTP.start(URL.host, URL.port, use_ssl: true, read_timeout: 30) { |h| h.request(req) }
    raise "Fireworks #{res.code}: #{res.body}" unless res.is_a?(Net::HTTPSuccess)  # add retry on 429/5xx
    JSON.parse(res.body)
  end
end
```

## Jev adapter (home)

Nearly a passthrough: all questions go in one call, and the response already has the right shape.

```ruby
class NParity::LLM::Jev < NParity::LLM::Backend
  URL = URI("https://api.typesafe.ai/v1/systemone")

  def initialize(model:, api_key:) = (@model, @api_key = model, api_key)

  def backend_id   = "jev:#{@model}"   # better: use the versioned id from the response, e.g. jev-1.13.0
  def capabilities = NParity::LLM::Capabilities.new(calibrated: true, max_options: 255,
                                                    calibrated_options: 255,
                                                    gives_reasons: false, batches_questions: true)

  def evaluate(state:, questions:, reasons: false)
    body = { model: @model, state: state, questions: questions.to_h { |q| [q.id, to_jev(q)] } }
    post(body)["answers"].to_h do |id, a|
      [id.to_sym, NParity::LLM::Answer.new(
        value: a["choice"] || a["score"] || a["noul"],
        probabilities: a["probabilities"] || { true => a["noul"], false => 1 - a["noul"] },
        confidence: a["confidence"] || (2 * (a["noul"] - 0.5)).abs,
        reason: nil,
        censored: false
      )]
    end
  end

  private

  def to_jev(q)
    type = q.class.name.split("::").last.downcase   # noul | choice | score
    { type: type, instructions: q.instructions, criteria: q.criteria }.compact
  end

  # post(body): same as Flash, against URL
end
```

## Cache decorator

Keyed per question, so a changed question only re-asks that one.

```ruby
class NParity::LLM::Cached < NParity::LLM::Backend
  def initialize(inner, store:) = (@inner, @store = inner, store)
  def backend_id   = @inner.backend_id
  def capabilities = @inner.capabilities

  def evaluate(state:, questions:, reasons: false)
    keyed  = questions.to_h { |q| [q, key(state, q, reasons)] }
    hits   = keyed.filter_map { |q, k| (a = @store.get(k)) && [q.id, a] }.to_h
    misses = questions.reject { |q| hits.key?(q.id) }
    fresh  = misses.empty? ? {} : @inner.evaluate(state: state, questions: misses, reasons: reasons)
    fresh.each { |id, a| @store.set(keyed[misses.find { _1.id == id }], a) }
    hits.merge(fresh)
  end

  private

  def key(state, q, reasons)
    Digest::SHA256.hexdigest([backend_id, state, q.to_h, reasons].to_json)
  end
end
```

REPORT (E7): Flash isn't bitwise deterministic at temperature 0 (same winner, small jitter, top-5 membership flips). The cache is what makes the demo replay identically, so warm it once and keep it.

## Thresholds, per backend

Tune these from the answer key run on each backend. Don't share numbers between backends.

```yaml
# config/thresholds.yml
"flash:deepseek-v4p1-flash-1017-us":
  auto_accept: 0.85   # placeholder until tuned; only meaningful when censored == false
  needs_review: 0.50
  # censored answers (k > 5): use the winner as a ranking, band as :review unless p(winner) > 0.99
"jev:jev-1.13.0":
  auto_accept: 0.90
  needs_review: 0.50
```

```ruby
band = case answer.confidence
       when (t["auto_accept"]..)  then :accepted
       when (t["needs_review"]..) then :review
       else                            :unmapped
       end
```

## Fake backend

Answers straight from the answer key. It gives deterministic tests, an offline demo fallback, and a ceiling to compare real backends against.

```ruby
class NParity::LLM::Fake < NParity::LLM::Backend
  # Looks up (state digest, question id) in the answer key and returns a one-hot Answer.
end
```

## Settled by the Fireworks report

- Model: `accounts/fireworks/routers/deepseek-v4p1-flash-1017-us` on `us.api.fireworks.ai`. Others return 403 on region.
- Reasoning off with `reasoning_effort: "none"` (or `thinking: {type: disabled}`). Without it there is no answer token.
- `top_logprobs` max is 5: calibrated up to 5 options, ranking-only up to ~30.
- Tokens: bare `"A"` / `"01"` in chat mode. Response shape is OpenAI's.
- No position bias (E6), so no permutation averaging.
- Prefix caching works (30 of 159 tokens cached). About $0.00007 and 0.6 s per call.

## Mapper rules that follow from it

- Shortlist to at most 30 deterministically (method filter, name overlap), dedupe near-identical candidates, then ask **once**. Never re-ask a trimmed list (E15: 0.998 dropped to 0.44).
- No Noul verification pass on the top 3 for mapping (E5). Use the Choice result directly.
- `None of these` stays in the full list as an escape hatch, but its probability isn't comparable across list lengths.
- If a full distribution over more than 5 options is ever needed, sample 8–16 times at temperature ~0.7 and count votes.
