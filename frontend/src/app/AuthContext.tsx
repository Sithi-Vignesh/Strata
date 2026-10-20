import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { getCurrentUser, login as loginRequest, logout as logoutRequest, register as registerRequest, type LoginInput, type RegisterInput } from "../api/product";
import { StrataApiError } from "../api/strata";
import type { User } from "../types/product";

type AuthStatus = "loading" | "authenticated" | "unauthenticated" | "error";
type AuthContextValue = { user: User | null; status: AuthStatus; error: Error | null; logoutPending: boolean; login: (input: LoginInput) => Promise<void>; register: (input: RegisterInput) => Promise<void>; logout: () => Promise<boolean>; retry: () => void; };
const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null); const [status, setStatus] = useState<AuthStatus>("loading"); const [error, setError] = useState<Error | null>(null); const [logoutPending, setLogoutPending] = useState(false); const requestVersion = useRef(0);
  const bootstrap = useCallback(async () => { const version = ++requestVersion.current; setStatus("loading"); setError(null); setUser(null); try { const currentUser = await getCurrentUser(); if (version !== requestVersion.current) return; setUser(currentUser); setStatus("authenticated"); } catch (caught) { if (version !== requestVersion.current) return; if (caught instanceof StrataApiError && caught.status === 401) setStatus("unauthenticated"); else { setError(asError(caught)); setStatus("error"); } } }, []);
  useEffect(() => { void bootstrap(); }, [bootstrap]);
  useEffect(() => {
    const expire = () => { ++requestVersion.current; setUser(null); setStatus("unauthenticated"); setError(null); };
    window.addEventListener("strata:session-expired", expire);
    return () => window.removeEventListener("strata:session-expired", expire);
  }, []);
  const login = useCallback(async (input: LoginInput) => { const version = ++requestVersion.current; setError(null); const currentUser = await loginRequest(input); if (version !== requestVersion.current) return; setUser(currentUser); setStatus("authenticated"); }, []);
  const register = useCallback(async (input: RegisterInput) => { const version = ++requestVersion.current; setError(null); const currentUser = await registerRequest(input); if (version !== requestVersion.current) return; setUser(currentUser); setStatus("authenticated"); }, []);
  const logout = useCallback(async () => { if (logoutPending) return false; const version = ++requestVersion.current; setLogoutPending(true); setError(null); try { await logoutRequest(); if (version !== requestVersion.current) return false; setUser(null); setStatus("unauthenticated"); return true; } catch (caught) { if (version === requestVersion.current) setError(asError(caught)); return false; } finally { setLogoutPending(false); } }, [logoutPending]);
  const value = useMemo(() => ({ user, status, error, logoutPending, login, register, logout, retry: () => { void bootstrap(); } }), [user, status, error, logoutPending, login, register, logout, bootstrap]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
export function useAuth() { const value = useContext(AuthContext); if (value === null) throw new Error("useAuth must be used within AuthProvider."); return value; }
function asError(value: unknown): Error { return value instanceof Error ? value : new Error("Could not reach the Strata backend."); }
