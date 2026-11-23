import { useState } from "react";

export function CopyField({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      // Clipboard API needs a secure context; fall back to selecting the text.
      const input = document.querySelector<HTMLInputElement>(`input[aria-label="${label}"]`);
      input?.select();
      document.execCommand("copy");
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="feed-row">
      <input readOnly value={value} onFocus={(e) => e.target.select()} aria-label={label} />
      <button onClick={copy}>{copied ? "Copied" : "Copy"}</button>
    </div>
  );
}
