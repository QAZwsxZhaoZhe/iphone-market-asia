const HKD_FORMATTER = new Intl.NumberFormat("zh-HK", {
  style: "currency",
  currency: "HKD",
  maximumFractionDigits: 0,
});

const NUMBER_FORMATTER = new Intl.NumberFormat("zh-HK");

export function formatHKD(value: number | null | undefined): string {
  return value === null || value === undefined
    ? "待估"
    : HKD_FORMATTER.format(value);
}

export function formatNumber(value: number | null | undefined): string {
  return value === null || value === undefined
    ? "0"
    : NUMBER_FORMATTER.format(value);
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "無紀錄";
  }
  return new Intl.DateTimeFormat("zh-HK", {
    timeZone: "Asia/Hong_Kong",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

export function formatDate(value: string | null | undefined): string {
  if (!value) {
    return "無紀錄";
  }
  return new Intl.DateTimeFormat("zh-HK", {
    timeZone: "Asia/Hong_Kong",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(value));
}

export function formatRelative(
  value: string | null | undefined,
  now = Date.now(),
): string {
  if (!value) {
    return "尚未成功";
  }
  const seconds = Math.max(
    0,
    Math.floor((now - new Date(value).getTime()) / 1000),
  );
  if (seconds < 60) {
    return "少於 1 分鐘";
  }
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) {
    return `${minutes} 分鐘前`;
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return `${hours} 小時前`;
  }
  return `${Math.floor(hours / 24)} 日前`;
}

export function freshnessLabel(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) {
    return "未採集";
  }
  if (seconds < 3600) {
    return `${Math.max(1, Math.floor(seconds / 60))} 分鐘`;
  }
  if (seconds < 86400) {
    return `${Math.floor(seconds / 3600)} 小時`;
  }
  return `${Math.floor(seconds / 86400)} 日`;
}

export function conditionLabel(value: string): string {
  return (
    {
      used: "二手",
      new: "全新",
      broken: "故障",
      accessory: "配件",
      wanted: "求購",
      rental: "出租",
    }[value] ?? value
  );
}

export function statusLabel(value: string): string {
  return (
    {
      active: "在售",
      sold: "已售",
      stale: "逾時",
      removed: "已下架",
      unknown: "未知",
      ok: "正常",
      partial: "部分完成",
      failed: "失敗",
      missing: "未運行",
      running: "執行中",
    }[value] ?? value
  );
}

export function statusTone(value: string): string {
  if (
    value === "ok" ||
    value === "active" ||
    value === "paid" ||
    value === "processing" ||
    value === "completed" ||
    value === "succeeded" ||
    value === "已成功"
  ) {
    return "positive";
  }
  if (
    value === "failed" ||
    value === "error" ||
    value === "cancelled" ||
    value === "refunded"
  ) {
    return "negative";
  }
  if (
    value === "partial" ||
    value === "stale" ||
    value === "running" ||
    value === "pending_payment" ||
    value === "refund_pending"
  ) {
    return "warning";
  }
  return "neutral";
}

export function orderStatusLabel(value: string): string {
  return (
    {
      pending_payment: "待付款",
      paid: "已付款",
      processing: "備貨中",
      shipped: "已發貨",
      completed: "已完成",
      cancelled: "已取消",
      refund_pending: "退款處理中",
      refunded: "已退款",
    }[value] ?? value
  );
}

export function paymentStatusLabel(value: string): string {
  return (
    {
      pending: "待付款",
      paid: "已付款",
      succeeded: "付款成功",
      cancelled: "已取消",
      refund_pending: "退款處理中",
      refunded: "已退款",
      failed: "付款失敗",
    }[value] ?? value
  );
}

export function fulfillmentStatusLabel(value: string): string {
  return (
    {
      unfulfilled: "待履約",
      processing: "備貨中",
      shipped: "已發貨",
      cancelled: "已取消",
      refunded: "已退款",
    }[value] ?? value
  );
}

export function ledgerEventLabel(value: string): string {
  return (
    {
      payment_captured: "付款入帳",
      merchant_settlement_created: "商家結算",
      refund_succeeded: "退款沖銷",
    }[value] ?? value
  );
}

export function valuationDelta(
  askingPrice: number | null,
  valuation: number | null,
): { label: string; tone: string } | null {
  if (!askingPrice || !valuation) {
    return null;
  }
  const ratio = ((askingPrice - valuation) / valuation) * 100;
  if (Math.abs(ratio) < 1) {
    return { label: "接近估值", tone: "neutral" };
  }
  return ratio < 0
    ? { label: `低於估值 ${Math.abs(ratio).toFixed(1)}%`, tone: "positive" }
    : { label: `高於估值 ${ratio.toFixed(1)}%`, tone: "warning" };
}

export function parsePositiveInt(
  value: string | string[] | undefined,
): number | undefined {
  const raw = Array.isArray(value) ? value[0] : value;
  if (!raw) {
    return undefined;
  }
  const parsed = Number.parseInt(raw, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined;
}
