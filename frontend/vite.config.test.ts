import { describe, expect, it } from "vitest";
import { devTunnelOriginOverride } from "./vite.config";

const publicOrigin = "https://5x62j38r-15174.inc1.devtunnels.ms";
const legitimateHeaders = [
  "Host", "localhost:15174",
  "Origin", "http://localhost:15174",
  "Referer", `${publicOrigin}/login`,
  "X-Forwarded-Host", "5x62j38r-15174.inc1.devtunnels.ms",
  "X-Forwarded-Proto", "https",
  "Sec-Fetch-Site", "same-origin",
];

function override(headers = legitimateHeaders, trustedOrigin = publicOrigin) {
  return devTunnelOriginOverride(headers, "POST", "/api/auth/login", 15174, trustedOrigin);
}

describe("Dev Tunnel Origin normalization", () => {
  it("restores the configured public origin only for the complete forwarded request signature", () => {
    expect(override()).toBe(publicOrigin);
  });

  it.each([
    ["cross-site browser request", "Sec-Fetch-Site", "cross-site"],
    ["foreign referer", "Referer", "https://attacker.invalid/login"],
    ["mismatched forwarded host", "X-Forwarded-Host", "attacker.invalid"],
    ["untrusted forwarded protocol", "X-Forwarded-Proto", "http"],
    ["wrong local listener", "Host", "localhost:15175"],
    ["foreign incoming origin", "Origin", "https://attacker.invalid"],
  ])("does not rewrite a %s", (_name, header, value) => {
    const headers = [...legitimateHeaders];
    headers[headers.findIndex((item) => item === header) + 1] = value;
    expect(override(headers)).toBeUndefined();
  });

  it("rejects duplicate security headers and non-Dev-Tunnel trusted origins", () => {
    expect(override([...legitimateHeaders, "Origin", "http://localhost:15174"])).toBeUndefined();
    expect(override(legitimateHeaders, "https://demo.example.com")).toBeUndefined();
  });

  it("does not rewrite safe methods or non-API paths", () => {
    expect(devTunnelOriginOverride(legitimateHeaders, "GET", "/api/auth/me", 15174, publicOrigin)).toBeUndefined();
    expect(devTunnelOriginOverride(legitimateHeaders, "POST", "/login", 15174, publicOrigin)).toBeUndefined();
  });
});
