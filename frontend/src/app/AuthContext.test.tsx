import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as productApi from "../api/product";
import { StrataApiError } from "../api/strata";
import { AuthProvider, useAuth } from "./AuthContext";

vi.mock("../api/product");
afterEach(() => { cleanup(); vi.resetAllMocks(); });

function Probe() { const auth = useAuth(); return <><p>{`${auth.status}:${auth.user?.name ?? "none"}`}</p><button onClick={() => { void auth.retry(); }} type="button">Retry</button><button onClick={() => { void auth.login({ email: "ada@example.local", password: "password" }); }} type="button">Login</button><button onClick={() => { void auth.register({ name: "Ada", email: "ada@example.local", password: "password" }); }} type="button">Register</button></>; }

describe("AuthContext", () => {
  it("bootstraps an existing browser session", async () => {
    vi.mocked(productApi.getCurrentUser).mockResolvedValue({ id: 2, name: "Ada", email: "ada@example.local" });
    render(<AuthProvider><Probe /></AuthProvider>);
    expect(await screen.findByText("authenticated:Ada")).toBeInTheDocument();
  });
  it("treats 401 as normal unauthenticated state and retries network failures", async () => {
    vi.mocked(productApi.getCurrentUser).mockRejectedValueOnce(new StrataApiError(0, "NETWORK_ERROR", "Offline")).mockRejectedValueOnce(new StrataApiError(401, "AUTHENTICATION_REQUIRED", "Authentication required."));
    render(<AuthProvider><Probe /></AuthProvider>);
    expect(await screen.findByText("error:none")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("unauthenticated:none")).toBeInTheDocument();
  });
  it("uses returned users directly after login and registration", async () => {
    vi.mocked(productApi.getCurrentUser).mockRejectedValue(new StrataApiError(401, "AUTHENTICATION_REQUIRED", "Authentication required."));
    vi.mocked(productApi.login).mockResolvedValue({ id: 3, name: "Ada", email: "ada@example.local" });
    vi.mocked(productApi.register).mockResolvedValue({ id: 4, name: "Grace", email: "grace@example.local" });
    render(<AuthProvider><Probe /></AuthProvider>);
    await screen.findByText("unauthenticated:none");
    fireEvent.click(screen.getByRole("button", { name: "Login" }));
    await waitFor(() => expect(screen.getByText("authenticated:Ada")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Register" }));
    await waitFor(() => expect(screen.getByText("authenticated:Grace")).toBeInTheDocument());
    expect(productApi.login).toHaveBeenCalledTimes(1);
    expect(productApi.register).toHaveBeenCalledTimes(1);
  });
});
