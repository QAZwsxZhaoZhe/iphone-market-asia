import assert from "node:assert/strict";
import test from "node:test";

import { parseVoiceListing } from "../src/lib/voice-listing.ts";

const variants = [
  {
    id: "14-pro-max-256",
    model: "iPhone 14 Pro Max",
    storage_gb: 256,
  },
  {
    id: "15-pro-128",
    model: "iPhone 15 Pro",
    storage_gb: 128,
  },
  {
    id: "16-pro-max-512",
    model: "iPhone 16 Pro Max",
    storage_gb: 512,
  },
  {
    id: "17-pro-max-1024",
    model: "iPhone 17 Pro Max",
    storage_gb: 1024,
  },
];

test("parses a complete Cantonese listing phrase", () => {
  const result = parseVoiceListing(
    "iPhone 十四 Pro Max 二百五十六 G 九成新 售價四千九百九十九 電池健康度八十八",
    variants,
  );

  assert.equal(result.variantId, "14-pro-max-256");
  assert.equal(result.conditionGrade, "B");
  assert.equal(result.priceHkd, 4999);
  assert.equal(result.batteryHealthPct, 88);
});

test("parses traditional Chinese and a suffix price", () => {
  const result = parseVoiceListing(
    "iPhone 十五 Pro 一百二十八 GB 九五新 賣五千二百港幣 電池 91%",
    variants,
  );

  assert.equal(result.variantId, "15-pro-128");
  assert.equal(result.conditionGrade, "A");
  assert.equal(result.priceHkd, 5200);
  assert.equal(result.batteryHealthPct, 91);
});

test("falls back to the largest plausible number when the price label is omitted", () => {
  const result = parseVoiceListing(
    "十六 Pro Max 五百一十二 G 九成新 四千五百九十九 電池八十四",
    variants,
  );

  assert.equal(result.variantId, "16-pro-max-512");
  assert.equal(result.conditionGrade, "B");
  assert.equal(result.priceHkd, 4599);
  assert.equal(result.batteryHealthPct, 84);
});

test("parses A plus condition and terabyte storage", () => {
  const result = parseVoiceListing(
    "iPhone 十七 Pro Max 1TB 全新未拆封 售價一萬二千八百",
    variants,
  );

  assert.equal(result.variantId, "17-pro-max-1024");
  assert.equal(result.conditionGrade, "A+");
  assert.equal(result.priceHkd, 12800);
});
