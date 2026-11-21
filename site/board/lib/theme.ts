export const themeStorageKey = "peira-theme";

export type ThemePreference = "system" | "light" | "dark";

export function readThemePreference(value: string | null): ThemePreference {
  return value === "light" || value === "dark" ? value : "system";
}

export function applyThemePreference(preference: ThemePreference) {
  if (preference === "system") {
    document.documentElement.removeAttribute("data-theme");
  } else {
    document.documentElement.dataset.theme = preference;
  }
}

// This runs in the head before the browser can paint. CSS handles the system preference.
export const initializeTheme = `try {
  const preference = localStorage.getItem(${JSON.stringify(themeStorageKey)});
  if (preference === "light" || preference === "dark") {
    document.documentElement.dataset.theme = preference;
  }
} catch {}`;
