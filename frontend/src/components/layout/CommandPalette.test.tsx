import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CommandPalette } from "./CommandPalette";

vi.mock("../../app/ProductContext", () => ({ useOptionalProduct: () => ({ selectedProjectId: 7, workspaces: [{ id: 2, name: "Team" }], selectWorkspace: vi.fn() }) }));
vi.mock("../../app/ThemeContext", () => ({ useTheme: () => ({ setPreference: vi.fn() }) }));

afterEach(cleanup);

describe("CommandPalette", () => {
  it("opens with Ctrl+K, focuses search, filters, navigates, and closes", async () => {
    render(<MemoryRouter><CommandPalette /><Location /></MemoryRouter>);
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const search = await screen.findByRole("combobox", { name: "Search commands" });
    await waitFor(() => expect(search).toHaveFocus());
    fireEvent.change(search, { target: { value: "Inbox" } });
    fireEvent.keyDown(search, { key: "Enter" });
    expect(screen.getByTestId("location")).toHaveTextContent("/inbox");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("suppresses shortcuts in editors and supports C in valid project context", () => {
    render(<MemoryRouter><textarea aria-label="Editor" /><CommandPalette /><Location /></MemoryRouter>);
    const editor = screen.getByLabelText("Editor");
    fireEvent.keyDown(editor, { key: "k", ctrlKey: true });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.keyDown(editor, { key: "c" });
    expect(screen.getByTestId("location")).toHaveTextContent("/");
    fireEvent.keyDown(window, { key: "c" });
    expect(screen.getByTestId("location")).toHaveTextContent("/tasks?create=1");
  });
});

function Location() { const location = useLocation(); return <output data-testid="location">{location.pathname}{location.search}</output>; }
