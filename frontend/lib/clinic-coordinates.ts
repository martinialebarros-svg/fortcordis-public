// Missing input must never become Number(null) / Number("") == 0.
export function clinicCoordinates(latitude: unknown, longitude: unknown) {
  const number = (value: unknown, bound: number): number | null => {
    if (typeof value !== "number" && typeof value !== "string") return null;
    if (typeof value === "string" && value.trim() === "") return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) && Math.abs(parsed) <= bound ? parsed : null;
  };
  const lat = number(latitude, 90);
  const lng = number(longitude, 180);
  // The legacy 0/0 placeholder is not a clinic location.
  if (lat === null || lng === null || (lat === 0 && lng === 0)) {
    return { latitude: null, longitude: null };
  }
  return { latitude: lat, longitude: lng };
}
