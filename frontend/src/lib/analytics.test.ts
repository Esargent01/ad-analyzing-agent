import { describe, expect, it } from "vitest";

import { deriveSignupSource } from "@/lib/analytics";

describe("deriveSignupSource", () => {
  it("buckets paid-medium UTMs as ad_campaign", () => {
    expect(
      deriveSignupSource({
        search: "?utm_source=facebook&utm_medium=paid_social&utm_campaign=q2",
        referrer: "",
        hostname: "kleiber.ai",
      }),
    ).toBe("ad_campaign");
    expect(
      deriveSignupSource({ search: "?utm_medium=cpc", hostname: "kleiber.ai" }),
    ).toBe("ad_campaign");
  });

  it("buckets known paid sources as ad_campaign even without utm_medium", () => {
    expect(
      deriveSignupSource({
        search: "?utm_source=meta",
        hostname: "kleiber.ai",
      }),
    ).toBe("ad_campaign");
    expect(
      deriveSignupSource({
        search: "?utm_source=google",
        hostname: "kleiber.ai",
      }),
    ).toBe("ad_campaign");
  });

  it("falls back to referral when utm_source is set but not paid", () => {
    expect(
      deriveSignupSource({
        search: "?utm_source=newsletter",
        hostname: "kleiber.ai",
      }),
    ).toBe("referral");
  });

  it("treats off-site referrers as referral", () => {
    expect(
      deriveSignupSource({
        search: "",
        referrer: "https://news.ycombinator.com/item?id=123",
        hostname: "kleiber.ai",
      }),
    ).toBe("referral");
  });

  it("ignores same-host referrers (treats as organic)", () => {
    expect(
      deriveSignupSource({
        search: "",
        referrer: "https://kleiber.ai/product",
        hostname: "kleiber.ai",
      }),
    ).toBe("organic");
  });

  it("returns organic when nothing identifies a source", () => {
    expect(
      deriveSignupSource({
        search: "",
        referrer: "",
        hostname: "kleiber.ai",
      }),
    ).toBe("organic");
  });
});
