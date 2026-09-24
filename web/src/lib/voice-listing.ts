export type VoiceListingVariant = {
  id: string;
  model: string;
  storage_gb: number;
};

export type VoiceListingDraft = {
  variantId?: string;
  variantLabel?: string;
  conditionGrade?: string;
  priceHkd?: number;
  batteryHealthPct?: number;
  appliedLabels: string[];
};

const CHINESE_DIGITS: Record<string, number> = {
  "〇": 0,
  零: 0,
  一: 1,
  二: 2,
  两: 2,
  三: 3,
  四: 4,
  五: 5,
  六: 6,
  七: 7,
  八: 8,
  九: 9,
};

const TRADITIONAL_TO_SIMPLIFIED: Record<string, string> = {
  價: "价",
  儲: "储",
  內: "内",
  存: "存",
  電: "电",
  體: "体",
  機: "机",
  賣: "卖",
  錢: "钱",
  級: "级",
  約: "约",
  為: "为",
  億: "亿",
};

function chineseSegmentToNumber(segment: string): number | null {
  if (!segment) {
    return null;
  }

  let total = 0;
  let section = 0;
  let digit = 0;
  let hasNumber = false;

  for (const character of segment) {
    if (character in CHINESE_DIGITS) {
      digit = CHINESE_DIGITS[character];
      hasNumber = true;
      continue;
    }

    const unit =
      character === "十"
        ? 10
        : character === "百"
          ? 100
          : character === "千"
            ? 1000
            : character === "万" || character === "萬"
              ? 10000
              : null;
    if (unit === null) {
      return null;
    }

    hasNumber = true;
    if (unit === 10000) {
      section = (section + (digit || 1)) * unit;
      total += section;
      section = 0;
    } else {
      section += (digit || 1) * unit;
    }
    digit = 0;
  }

  return hasNumber ? total + section + digit : null;
}

function replaceChineseNumbers(value: string): string {
  return value.replace(/[〇零一二两三四五六七八九十百千万萬]+/g, (match) => {
    const number = chineseSegmentToNumber(match);
    return number === null ? match : String(number);
  });
}

function normalizeSpeech(value: string): string {
  const simplified = Array.from(value.toLowerCase(), (character) =>
    TRADITIONAL_TO_SIMPLIFIED[character] ?? character,
  ).join("");
  return replaceChineseNumbers(
    simplified
      .replace(/九五(?=新|成新)/g, "95")
      .replace(/九九(?=新|成新)/g, "99"),
  )
    .replace(/[，。！？、,.!?;；:：]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function parseCondition(compact: string): string | undefined {
  if (
    compact.includes("a+") ||
    compact.includes("a加") ||
    compact.includes("全新") ||
    compact.includes("未拆封") ||
    compact.includes("未开封")
  ) {
    return "A+";
  }
  if (
    compact.includes("95新") ||
    compact.includes("95成新") ||
    compact.includes("九五新") ||
    compact.includes("9.5成新") ||
    compact.includes("9成5新") ||
    compact.includes("a级")
  ) {
    return "A";
  }
  if (
    compact.includes("9成新") ||
    compact.includes("九成新") ||
    compact.includes("9新") ||
    compact.includes("b级")
  ) {
    return "B";
  }
  if (
    compact.includes("8成新") ||
    compact.includes("八成新") ||
    compact.includes("8新") ||
    compact.includes("c级")
  ) {
    return "C";
  }
  if (
    compact.includes("7成新") ||
    compact.includes("七成新") ||
    compact.includes("7新") ||
    compact.includes("d级")
  ) {
    return "D";
  }
  return undefined;
}

function parseBattery(compact: string): number | undefined {
  const match = compact.match(
    /(?:电池健康度|电池健康|电池|battery)(?:百分之|是|为|有)?([0-9]{1,3})/,
  );
  if (!match) {
    return undefined;
  }
  const value = Number(match[1]);
  return value >= 0 && value <= 100 ? value : undefined;
}

function parsePrice(compact: string): number | undefined {
  const labelled = compact.match(
    /(?:售价|价格|价钱|卖价|出售|出手|卖|售|hkd|港币|港元)(?:是|为|约|大约)?([0-9]+(?:\.[0-9]+)?)/,
  );
  const suffixed = compact.match(/([0-9]+(?:\.[0-9]+)?)(?:港币|港元|hkd)/);
  const value = Number(labelled?.[1] ?? suffixed?.[1]);
  return Number.isFinite(value) && value > 0 ? value : undefined;
}

function parseStorage(compact: string): number | undefined {
  if (/(?:1tb|1t|一tb|一t)(?:存储|内存)?/.test(compact)) {
    return 1024;
  }
  if (/(?:2tb|2t|二tb|二t)(?:存储|内存)?/.test(compact)) {
    return 2048;
  }
  const match = compact.match(/(128|256|512|1024)(?:gb|g|存储|内存)?/);
  return match ? Number(match[1]) : undefined;
}

function parseModel(
  compact: string,
  variants: VoiceListingVariant[],
): { variantId?: string; variantLabel?: string; storageGb?: number } {
  const generation = compact.match(/(14|15|16|17)(?=pro|promax)/)?.[1];
  if (!generation) {
    return {};
  }

  const storageGb = parseStorage(compact);
  const isMax =
    compact.includes("promax") ||
    compact.includes("麦克斯") ||
    /(?:14|15|16|17)max/.test(compact);
  const model = `iPhone ${generation} Pro${isMax ? " Max" : ""}`;
  const variant = variants.find(
    (candidate) =>
      candidate.model === model &&
      (storageGb === undefined || candidate.storage_gb === storageGb),
  );

  if (!variant) {
    return { storageGb };
  }
  return {
    variantId: variant.id,
    variantLabel: `${variant.model} · ${formatStorage(variant.storage_gb)}`,
    storageGb: variant.storage_gb,
  };
}

function formatStorage(storageGb: number): string {
  return storageGb >= 1024 ? `${storageGb / 1024}TB` : `${storageGb}GB`;
}

function findFallbackPrice(
  compact: string,
  ignoredNumbers: Array<number | undefined>,
): number | undefined {
  const ignored = new Set(ignoredNumbers.filter((value) => value !== undefined));
  return compact
    .match(/\d+(?:\.\d+)?/g)
    ?.map(Number)
    .filter((value) => Number.isFinite(value) && value >= 500 && !ignored.has(value))
    .sort((left, right) => right - left)[0];
}

export function parseVoiceListing(
  transcript: string,
  variants: VoiceListingVariant[],
): VoiceListingDraft {
  const normalized = normalizeSpeech(transcript);
  const compact = normalized.replace(/[^a-z0-9+\u4e00-\u9fff]/g, "");
  const model = parseModel(compact, variants);
  const conditionGrade = parseCondition(compact);
  const batteryHealthPct = parseBattery(compact);
  const explicitPrice = parsePrice(compact);
  const priceHkd =
    explicitPrice ??
    findFallbackPrice(compact, [
      batteryHealthPct,
      model.storageGb,
      Number(compact.match(/(14|15|16|17)(?=pro|promax)/)?.[1]),
    ]);
  const appliedLabels: string[] = [];

  if (model.variantLabel) {
    appliedLabels.push(`機型 ${model.variantLabel}`);
  }
  if (conditionGrade) {
    appliedLabels.push(`成色 ${conditionGrade}`);
  }
  if (priceHkd !== undefined) {
    appliedLabels.push(`售價 HK$${priceHkd.toLocaleString("zh-HK")}`);
  }
  if (batteryHealthPct !== undefined) {
    appliedLabels.push(`電池 ${batteryHealthPct}%`);
  }

  return {
    variantId: model.variantId,
    variantLabel: model.variantLabel,
    conditionGrade,
    priceHkd,
    batteryHealthPct,
    appliedLabels,
  };
}
