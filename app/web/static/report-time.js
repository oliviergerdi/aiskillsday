const reportTimeOptions = {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
  timeZoneName: "short",
};
const reportTimeFormat = new Intl.DateTimeFormat(undefined, reportTimeOptions);
const reportTimeWithYear = new Intl.DateTimeFormat(undefined, { ...reportTimeOptions, year: "numeric" });

function formatReportTime(iso, withYear = false) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return (withYear ? reportTimeWithYear : reportTimeFormat).format(date);
}

function localizeReportTimes(root) {
  for (const time of root.querySelectorAll("time[data-local-time]")) {
    time.textContent = formatReportTime(time.dateTime, time.hasAttribute("data-with-year"));
  }
  for (const option of root.querySelectorAll("option[data-local-time]")) {
    option.textContent = `${formatReportTime(option.dataset.localTime)} · ${option.value}`;
  }
}

localizeReportTimes(document);
document.addEventListener("htmx:afterSwap", event => localizeReportTimes(event.detail.target));
