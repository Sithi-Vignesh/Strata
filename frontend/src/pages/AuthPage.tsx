import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { StrataApiError } from "../api/strata";
import { useAuth } from "../app/AuthContext";

export function AuthPage({ mode }: { mode: "login" | "register" }) {
  const auth = useAuth();
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  const registering = mode === "register";
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); if (pending) return; setPending(true); setMessage(null);
    const values = new FormData(event.currentTarget); const email = String(values.get("email") ?? ""); const password = String(values.get("password") ?? "");
    try { if (registering) await auth.register({ name: String(values.get("name") ?? ""), email, password }); else await auth.login({ email, password }); }
    catch (error) { if (error instanceof StrataApiError && error.status === 401) setMessage("Invalid email or password."); else if (error instanceof StrataApiError && error.status === 409) setMessage("An account with that email already exists."); else if (error instanceof StrataApiError && error.status === 422) setMessage("Please check the details and try again."); else setMessage("Could not reach Strata. Please try again."); }
    finally { setPending(false); }
  };
  return <main className="auth-page">
    <section className="auth-form-side">
      <div className="auth-form-wrap">
        <Link className="auth-wordmark" to="/"><span className="wordmark-mark" aria-hidden="true"><i /><i /><i /></span><span>STRATA</span></Link>
        <div className="auth-heading"><span className="kicker">{registering ? "Start organizing" : "Welcome to Strata"}</span><h1>{registering ? "Create your workspace" : "Welcome back"}</h1><p>{registering ? "Create your account and start with a private workspace built for focused work." : "Sign in to get back to the work that matters."}</p></div>
        {auth.status === "error" && <div className="auth-alert" role="alert">Could not restore your session. <button onClick={auth.retry} type="button">Retry</button></div>}
        {message && <div className="auth-alert" role="alert">{message}</div>}
        <form className="auth-form" onSubmit={submit}>
          {registering && <Field autoComplete="name" label="Name" name="name" placeholder="Your name" type="text" />}
          <Field autoComplete="email" label="Email" name="email" placeholder="you@company.com" type="email" />
          <label className="auth-field"><span>Password</span><span className="password-field"><input autoComplete={registering ? "new-password" : "current-password"} name="password" placeholder={registering ? "At least 8 characters" : "Enter your password"} required type={showPassword ? "text" : "password"} /><button aria-label={showPassword ? "Hide password" : "Show password"} onClick={() => setShowPassword((value) => !value)} type="button">{showPassword ? "Hide" : "Show"}</button></span></label>
          <button className="button button-primary auth-submit" disabled={pending} type="submit">{pending ? <><span className="spinner" />Please wait…</> : registering ? "Create account" : "Sign in"}</button>
        </form>
        <p className="auth-switch">{registering ? "Already have an account? " : "New to Strata? "}<Link to={registering ? "/login" : "/register"}>{registering ? "Sign in" : "Create account"}</Link></p>
        <p className="auth-security">Secure, session-based authentication · Your workspace data stays private</p>
      </div>
    </section>
    <aside className="auth-art" aria-hidden="true"><div className="auth-glow auth-glow-one" /><div className="auth-glow auth-glow-two" /><div className="auth-art-content"><div className="auth-art-mark"><span /><span /><span /></div><p>Plan clearly.<br />Move work forward.</p><div className="auth-demo"><div className="auth-demo-top"><i /><span /><b /></div><div className="auth-demo-body"><nav><i /><i /><i /><i /></nav><section><header /><div className="auth-demo-columns"><article><b /><span /><span /></article><article><b /><span /><span /><span /></article><article><b /><span /></article></div></section></div></div><blockquote>“A calm place for teams to turn plans into progress.”</blockquote></div></aside>
  </main>;
}

function Field({ label, name, type, placeholder, autoComplete }: { label: string; name: string; type: string; placeholder: string; autoComplete: string }) { return <label className="auth-field"><span>{label}</span><input autoComplete={autoComplete} name={name} placeholder={placeholder} required type={type} /></label>; }
