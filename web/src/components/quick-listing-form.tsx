"use client";

import { Mic, Square } from "lucide-react";
import {
  type FormEvent,
  useEffect,
  useRef,
  useState,
} from "react";

import { SubmitButton } from "@/components/submit-button";
import type { Merchant, VariantMeta } from "@/lib/types";
import {
  parseVoiceListing,
  type VoiceListingDraft,
} from "@/lib/voice-listing";

type SpeechAlternativeLike = {
  transcript: string;
};

type SpeechResultLike = {
  isFinal: boolean;
  length: number;
  [index: number]: SpeechAlternativeLike;
};

type SpeechEventLike = {
  resultIndex: number;
  results: {
    length: number;
    [index: number]: SpeechResultLike;
  };
};

type SpeechErrorEventLike = {
  error: string;
};

type SpeechRecognitionLike = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  maxAlternatives: number;
  onend: (() => void) | null;
  onerror: ((event: SpeechErrorEventLike) => void) | null;
  onresult: ((event: SpeechEventLike) => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
};

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike;

type SpeechWindow = Window & {
  SpeechRecognition?: SpeechRecognitionConstructor;
  webkitSpeechRecognition?: SpeechRecognitionConstructor;
};

type QuickListingFormProps = {
  action: (formData: FormData) => Promise<void>;
  merchants: Merchant[];
  variants: VariantMeta[];
};

const CONDITION_GRADES = ["A+", "A", "B", "C", "D"];

export function QuickListingForm({
  action,
  merchants,
  variants,
}: QuickListingFormProps) {
  const [merchantId, setMerchantId] = useState(merchants[0]?.id ?? "");
  const [variantId, setVariantId] = useState(variants[0]?.id ?? "");
  const [conditionGrade, setConditionGrade] = useState("B");
  const [priceHkd, setPriceHkd] = useState("");
  const [batteryHealthPct, setBatteryHealthPct] = useState("");
  const [images, setImages] = useState("");
  const [transcript, setTranscript] = useState("");
  const [status, setStatus] = useState("");
  const [appliedLabels, setAppliedLabels] = useState<string[]>([]);
  const [isListening, setIsListening] = useState(false);
  const [isSupported, setIsSupported] = useState<boolean | null>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const finalTranscriptRef = useRef("");

  useEffect(() => {
    const speechWindow = window as SpeechWindow;
    setIsSupported(
      Boolean(
        speechWindow.SpeechRecognition ??
          speechWindow.webkitSpeechRecognition,
      ),
    );
    return () => {
      recognitionRef.current?.abort();
    };
  }, []);

  function applyDraft(draft: VoiceListingDraft) {
    if (draft.variantId) {
      setVariantId(draft.variantId);
    }
    if (draft.conditionGrade) {
      setConditionGrade(draft.conditionGrade);
    }
    if (draft.priceHkd !== undefined) {
      setPriceHkd(String(draft.priceHkd));
    }
    if (draft.batteryHealthPct !== undefined) {
      setBatteryHealthPct(String(draft.batteryHealthPct));
    }
    setAppliedLabels(draft.appliedLabels);
    setStatus(
      draft.appliedLabels.length
        ? "已填入識別結果，請確認後上架。"
        : "未識別到機型、成色、售價或電池資料，請再說一次。",
    );
  }

  function startListening() {
    const speechWindow = window as SpeechWindow;
    const Recognition =
      speechWindow.SpeechRecognition ??
      speechWindow.webkitSpeechRecognition;
    if (!Recognition) {
      setStatus("此瀏覽器不支援語音輸入。");
      return;
    }

    recognitionRef.current?.abort();
    finalTranscriptRef.current = "";
    setTranscript("");
    setAppliedLabels([]);
    setStatus("正在聆聽…");

    const recognition = new Recognition();
    recognition.lang = "zh-HK";
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;
    recognition.onresult = (event) => {
      let finalText = "";
      let interimText = "";
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index];
        const text = result[0]?.transcript ?? "";
        if (result.isFinal) {
          finalText += text;
        } else {
          interimText += text;
        }
      }

      if (finalText) {
        finalTranscriptRef.current += finalText;
        applyDraft(parseVoiceListing(finalTranscriptRef.current, variants));
      }
      setTranscript(`${finalTranscriptRef.current}${interimText}`);
    };
    recognition.onerror = (event) => {
      setIsListening(false);
      setStatus(
        event.error === "not-allowed" || event.error === "service-not-allowed"
          ? "沒有麥克風權限，請在瀏覽器允許後再試。"
          : "沒有聽清楚，請再試一次。",
      );
    };
    recognition.onend = () => {
      setIsListening(false);
    };
    recognitionRef.current = recognition;

    try {
      recognition.start();
      setIsListening(true);
    } catch {
      setIsListening(false);
      setStatus("語音輸入暫時無法啟動，請稍後再試。");
    }
  }

  function stopListening() {
    recognitionRef.current?.stop();
    setIsListening(false);
    setStatus("已完成語音輸入，請確認填入的資料。");
  }

  function submitQuickListing(event: FormEvent<HTMLFormElement>) {
    recognitionRef.current?.stop();
    if (!event.currentTarget.checkValidity()) {
      event.preventDefault();
    }
  }

  return (
    <form
      action={action}
      className="catalog-form catalog-form--wide"
      onSubmit={submitQuickListing}
    >
      <div className="voice-listing">
        <button
          aria-label={isListening ? "停止語音輸入" : "開始語音輸入"}
          aria-pressed={isListening}
          className={[
            "button",
            "button--ghost",
            "voice-listing__button",
            isListening ? "voice-listing__button--active" : "",
          ]
            .filter(Boolean)
            .join(" ")}
          disabled={isSupported === false}
          onClick={isListening ? stopListening : startListening}
          title={isListening ? "停止語音輸入" : "開始語音輸入"}
          type="button"
        >
          {isListening ? (
            <Square size={14} aria-hidden="true" />
          ) : (
            <Mic size={14} aria-hidden="true" />
          )}
          {isListening ? "停止" : "語音填寫"}
        </button>

        <div className="voice-listing__content">
          <span className="voice-listing__status" aria-live="polite">
            {status ||
              (isSupported === false
                ? "此瀏覽器不支援語音輸入。"
                : "說出機型、容量、成色、售價及電池健康度。")}
          </span>
          {transcript ? (
            <p className="voice-listing__transcript">「{transcript}」</p>
          ) : null}
          {appliedLabels.length ? (
            <div className="voice-listing__chips">
              {appliedLabels.map((label) => (
                <span className="voice-chip" key={label}>
                  {label}
                </span>
              ))}
            </div>
          ) : null}
        </div>
      </div>

      <div className="field">
        <label htmlFor="quick-merchant">商家</label>
        <select
          className="select"
          id="quick-merchant"
          name="merchant_id"
          onChange={(event) => setMerchantId(event.target.value)}
          required
          value={merchantId}
        >
          {merchants.map((merchant) => (
            <option key={merchant.id} value={merchant.id}>
              {merchant.display_name}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label htmlFor="quick-variant">機型容量</label>
        <select
          className="select"
          id="quick-variant"
          name="phone_variant_id"
          onChange={(event) => setVariantId(event.target.value)}
          required
          value={variantId}
        >
          {variants.map((variant) => (
            <option key={variant.id} value={variant.id}>
              {variant.model} · {variant.storage_label}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label htmlFor="quick-grade">成色</label>
        <select
          className="select"
          id="quick-grade"
          name="condition_grade"
          onChange={(event) => setConditionGrade(event.target.value)}
          value={conditionGrade}
        >
          {CONDITION_GRADES.map((grade) => (
            <option key={grade} value={grade}>
              {grade}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label htmlFor="quick-price">售價 HKD</label>
        <input
          className="input"
          id="quick-price"
          min="0.01"
          name="price_hkd"
          onChange={(event) => setPriceHkd(event.target.value)}
          required
          step="0.01"
          type="number"
          value={priceHkd}
        />
      </div>
      <div className="field">
        <label htmlFor="quick-battery">電池健康度 %（選填）</label>
        <input
          className="input"
          id="quick-battery"
          max="100"
          min="0"
          name="battery_health_pct"
          onChange={(event) => setBatteryHealthPct(event.target.value)}
          type="number"
          value={batteryHealthPct}
        />
      </div>
      <div className="field field--wide">
        <label htmlFor="quick-images">圖片網址（選填）</label>
        <textarea
          className="input"
          id="quick-images"
          name="images"
          onChange={(event) => setImages(event.target.value)}
          placeholder="每行一個網址"
          rows={2}
          value={images}
        />
      </div>
      <div className="catalog-form__action">
        <SubmitButton>立即上架</SubmitButton>
      </div>
    </form>
  );
}
