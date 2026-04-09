import { describe, expect, it } from "vitest";

import {
  formatCurrency,
  formatDateLabel,
  formatIntComma,
  formatOneDecimal,
  formatPct,
  formatSignedPct,
} from "@/lib/format";

describe("formatCurrency", () => {
  it("formats small values with cents", () => {
    expect(formatCurrency(12.34)).toBe("$12.34");
    expect(formatCurrency("0.5")).toBe("$0.50");
  });

  it("rounds large values to whole dollars with commas", () => {
    expect(formatCurrency(1234.56)).toBe("$1,235");
    expect(formatCurrency("12345")).toBe("$12,345");
  });

  it("falls back to 0 on null/undefined/garbage", () => {
    expect(formatCurrency(null)).toBe("$0.00");
    expect(formatCurrency(undefined)).toBe("$0.00");
    expect(formatCurrency("not-a-number")).toBe("$0.00");
  });
});

describe("formatIntComma", () => {
  it("adds thousands separators", () => {
    expect(formatIntComma(1234567)).toBe("1,234,567");
    expect(formatIntComma("5000")).toBe("5,000");
  });
});

describe("formatOneDecimal", () => {
  it("always shows one decimal place", () => {
    expect(formatOneDecimal(2)).toBe("2.0");
    expect(formatOneDecimal(2.456)).toBe("2.5");
  });
});

describe("formatPct", () => {
  it("treats values < 1 as fractions", () => {
    expect(formatPct(0.123)).toBe("12.3%");
  });

  it("passes through values >= 1", () => {
    expect(formatPct(12.3)).toBe("12.3%");
  });
});

describe("formatSignedPct", () => {
  it("adds a leading + for non-negative", () => {
    expect(formatSignedPct(0.12)).toBe("+12%");
    expect(formatSignedPct(0)).toBe("+0%");
  });

  it("keeps the negative sign for losses", () => {
    expect(formatSignedPct(-0.04)).toBe("-4%");
  });
});

describe("formatDateLabel", () => {
  it("renders an abbreviated en-US date", () => {
    expect(formatDateLabel("2026-04-09")).toBe("Apr 9, 2026");
  });

  it("returns the raw value for garbage input", () => {
    expect(formatDateLabel("not-a-date")).toBe("not-a-date");
  });
});
