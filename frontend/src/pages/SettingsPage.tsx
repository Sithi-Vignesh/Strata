import { PageHeader } from "../components/layout/PageHeader";
import { useAuth } from "../app/AuthContext";
import { useTheme, type ThemePreference } from "../app/ThemeContext";
import { Avatar } from "../components/ui/Avatar";

const options: Array<{ value: ThemePreference; label: string; description: string; preview: string }> = [
  { value: "light", label: "Light", description: "Bright, calm surfaces for daytime work.", preview: "theme-preview-light" },
  { value: "dark", label: "Dark", description: "Low-glare contrast for focused work.", preview: "theme-preview-dark" },
  { value: "system", label: "System", description: "Match your device appearance automatically.", preview: "theme-preview-system" },
];

export function SettingsPage() {
  const auth = useAuth();
  const theme = useTheme();
  return <section className="page-container page-narrow">
    <PageHeader eyebrow="Preferences" title="Settings" description="Choose how Strata looks and review your signed-in account." />
    <section className="settings-section" aria-labelledby="appearance-heading">
      <div className="section-heading"><div><h2 id="appearance-heading">Appearance</h2><p>Your preference is saved in this browser.</p></div><span className="status-pill">{theme.resolvedTheme} active</span></div>
      <div className="theme-grid">
        {options.map((option) => <button aria-pressed={theme.preference === option.value} className="theme-option" key={option.value} onClick={() => theme.setPreference(option.value)} type="button">
          <span className={`theme-preview ${option.preview}`}><i /><i /><i /></span>
          <span><strong>{option.label}</strong><small>{option.description}</small></span>
          <span className="theme-check" aria-hidden="true">{theme.preference === option.value ? "✓" : ""}</span>
        </button>)}
      </div>
    </section>
    {auth.user && <section className="settings-section" aria-labelledby="account-heading">
      <div className="section-heading"><div><h2 id="account-heading">Account</h2><p>Your current Strata session.</p></div></div>
      <div className="account-card"><Avatar name={auth.user.name} size="lg" /><div><strong>{auth.user.name}</strong><p>{auth.user.email}</p></div><button className="button button-secondary" disabled={auth.logoutPending} onClick={() => void auth.logout()} type="button">{auth.logoutPending ? "Signing out…" : "Sign out"}</button></div>
    </section>}
  </section>;
}
