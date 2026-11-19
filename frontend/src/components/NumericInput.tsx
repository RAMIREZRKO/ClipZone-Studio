import { useEffect, useState, type InputHTMLAttributes } from 'react';

type Props = Omit<InputHTMLAttributes<HTMLInputElement>,
  'value' | 'defaultValue' | 'type' | 'inputMode' | 'min' | 'max' | 'step' | 'onChange' | 'onBlur' | 'onKeyDown'> & {
  value: number | null;
  min: number;
  max: number;
  precision?: number;
  step?: number;
  onCommit: (value: number) => void;
  onPreview?: (value: number | null) => void;
};

function readNumber(text: string): number | undefined {
  const normalized = text.trim().replace(',', '.');
  if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(normalized)) return undefined;
  const number = Number(normalized);
  return Number.isFinite(number) ? number : undefined;
}

export function NumericInput({ value, min, max, precision = 0, step = 10 ** -precision, onCommit, onPreview, ...attributes }: Props) {
  const [draft, setDraft] = useState<string | null>(null);

  useEffect(() => { setDraft(null); }, [value]);

  const text = draft ?? (value === null ? '' : String(value));
  const parsed = readNumber(text);
  const withinBounds = (number: number) => Math.max(min, Math.min(max, Number(number.toFixed(precision))));

  function edit(text: string) {
    setDraft(text);
    if (!onPreview) return;
    const parsed = readNumber(text);
    const next = parsed === undefined || max < min ? null : withinBounds(parsed);
    onPreview(next === value ? null : next);
  }

  function clearDraft() {
    setDraft(null);
    onPreview?.(null);
  }

  function commit() {
    if (draft === null) return;
    clearDraft();
    if (parsed === undefined || max < min) return;
    const next = withinBounds(parsed);
    if (next !== value) onCommit(next);
  }

  return <input {...attributes} type="text" inputMode={precision ? 'decimal' : 'numeric'} role="spinbutton"
    data-numeric-input aria-valuemin={min} aria-valuemax={max}
    aria-valuenow={parsed !== undefined && parsed >= min && parsed <= max ? parsed : undefined}
    value={text} onChange={event => edit(event.target.value)} onBlur={commit}
    onKeyDown={event => {
      if (event.nativeEvent.isComposing) return;
      if (event.key === 'Enter') {
        event.preventDefault();
        commit();
      } else if (event.key === 'Escape' && draft !== null) {
        event.preventDefault();
        clearDraft();
      } else if ((event.key === 'ArrowUp' || event.key === 'ArrowDown') &&
                 !event.altKey && !event.ctrlKey && !event.shiftKey && !event.metaKey && max >= min) {
        event.preventDefault();
        const current = parsed ?? value ?? min;
        edit(String(withinBounds(current + (event.key === 'ArrowUp' ? step : -step))));
      }
    }}/>;
}
