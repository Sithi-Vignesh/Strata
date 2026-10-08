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
  const login = useCallback(async (input: LoginInput) => { setError(null); const currentUser = await loginRequest(input); ++requestVersion.current; setUser(currentUser); setStatus("authenticated"); }, []);
  const register = useCallback(async (input: RegisterInput) => { setError(null); const currentUser = await registerRequest(input); ++requestVersion.current; setUser(currentUser); setStatus("authenticated"); }, []);
  const logout = useCallback(async () => { if (logoutPending) return false; setLogoutPending(true); setError(null); try { await logoutRequest(); ++requestVersion.current; setUser(null); setStatus("unauthenticated"); return true; } catch (caught) { setError(asError(caught)); return false; } finally { setLogoutPending(false); } }, [logoutPending]);
  const value = useMemo(() => ({ user, status, error, logoutPending, login, register, logout, retry: () => { void bootstrap(); } }), [user, status, error, logoutPending, login, register, logout, bootstrap]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
export function useAuth() { const value = useContext(AuthContext); if (value === null) throw new Error("useAuth must be used within AuthProvider."); return value; }
function asError(value: unknown): Error { return value instanceof Error ? value : new Error("Could not reach the Strata backend."); }
