import type { SVGProps } from "react";

export type NavIconName = "overview" | "tasks" | "board" | "sql" | "engine";

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
      {name === "board" && <path d="M4.5 4.5h4.5v15H4.5zM10.5 4.5H15v10h-4.5zM16.5 4.5H21v6h-4.5z" />}
      {name === "sql" && <path d="m8.5 7-5 5 5 5M15.5 7l5 5-5 5M13.5 5l-3 14" />}
      {name === "engine" && <path d="M19.5 6c0 1.9-3.4 3.5-7.5 3.5S4.5 7.9 4.5 6 7.9 2.5 12 2.5 19.5 4.1 19.5 6Zm0 0v6c0 1.9-3.4 3.5-7.5 3.5S4.5 13.9 4.5 12V6m15 6v6c0 1.9-3.4 3.5-7.5 3.5S4.5 19.9 4.5 18v-6" />}
    </svg>
  );
}
