import type { SVGProps } from "react";

export type NavIconName = "overview" | "tasks" | "projects" | "list" | "board" | "members" | "inbox" | "sql" | "engine" | "settings" | "menu";

interface NavIconProps extends SVGProps<SVGSVGElement> {
  name: NavIconName;
}

export function NavIcon({ name, ...props }: NavIconProps) {
  const common = {
    fill: "none",
    stroke: "currentColor",
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    strokeWidth: 1.75,
  };

  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" {...props} {...common}>
      {name === "overview" && <path d="m3.5 10 8.5-6.5 8.5 6.5v9.5a1 1 0 0 1-1 1h-15a1 1 0 0 1-1-1Z M9 20.5v-6h6v6" />}
      {name === "tasks" && <path d="m5 7 1.5 1.5L9 5.8 M12 7h7 M5 13l1.5 1.5L9 11.8 M12 13h7 M5 19l1.5 1.5L9 17.8 M12 19h7" />}
      {name === "projects" && <path d="M3.5 7.5h7l2-2h8v13h-17z M3.5 10.5h17" />}
      {name === "list" && <path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01" />}
      {name === "board" && <path d="M4.5 4.5h4.5v15H4.5zM10.5 4.5H15v10h-4.5zM16.5 4.5H21v6h-4.5z" />}
      {name === "members" && <path d="M16 20v-1.5a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4V20M9 10.5a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM16 4.5a4 4 0 0 1 0 7.5M22 20v-1.5a4 4 0 0 0-3-3.7" />}
      {name === "inbox" && <path d="M4 5.5h16v13H4zM4 14h4l1.5 2h5l1.5-2h4" />}
      {name === "sql" && <path d="m8.5 7-5 5 5 5M15.5 7l5 5-5 5M13.5 5l-3 14" />}
      {name === "engine" && <path d="M19.5 6c0 1.9-3.4 3.5-7.5 3.5S4.5 7.9 4.5 6 7.9 2.5 12 2.5 19.5 4.1 19.5 6Zm0 0v6c0 1.9-3.4 3.5-7.5 3.5S4.5 13.9 4.5 12V6m15 6v6c0 1.9-3.4 3.5-7.5 3.5S4.5 19.9 4.5 18v-6" />}
      {name === "settings" && <path d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Zm7.4-3.5a7 7 0 0 0-.1-1l2-1.5-2-3.4-2.4 1a8 8 0 0 0-1.8-1L14.8 3h-4l-.4 3.1a8 8 0 0 0-1.8 1l-2.4-1-2 3.4 2 1.5a7 7 0 0 0 0 2l-2 1.5 2 3.4 2.4-1a8 8 0 0 0 1.8 1l.4 3.1h4l.4-3.1a8 8 0 0 0 1.8-1l2.4 1 2-3.4-2-1.5a7 7 0 0 0 .1-1Z" />}
      {name === "menu" && <path d="M4 7h16M4 12h16M4 17h16" />}
    </svg>
  );
}
