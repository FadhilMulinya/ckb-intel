/**
 * Formats a Date as a human-readable string for API responses (e.g.
 * "Aug 2, 2026, 8:39 AM UTC") instead of a raw ISO-8601 timestamp.
 * Storage in MongoDB is untouched -- this only affects what gets sent
 * back over HTTP. Fixed to UTC so the output doesn't depend on the
 * server's local timezone.
 */
export function toHumanDate(value: Date | string | null | undefined): string | null {
  if (!value) return null;
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return null;

  return (
    new Intl.DateTimeFormat("en-US", {
      dateStyle: "medium",
      timeStyle: "short",
      timeZone: "UTC",
    }).format(date) + " UTC"
  );
}
