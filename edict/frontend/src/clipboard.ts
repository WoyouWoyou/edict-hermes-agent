export async function copyText(text: string): Promise<boolean> {
  const value = text || '';
  if (!value) return false;

  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      return true;
    }
  } catch {
    // Fall through to the selection-based copy path below.
  }

  const textarea = document.createElement('textarea');
  textarea.value = value;
  textarea.setAttribute('readonly', 'true');
  textarea.style.position = 'fixed';
  textarea.style.left = '-9999px';
  textarea.style.top = '0';
  document.body.appendChild(textarea);

  const selection = document.getSelection();
  const previousRange = selection && selection.rangeCount > 0 ? selection.getRangeAt(0) : null;

  textarea.focus();
  textarea.select();
  textarea.setSelectionRange(0, textarea.value.length);

  let ok = false;
  try {
    ok = document.execCommand('copy');
  } catch {
    ok = false;
  }

  document.body.removeChild(textarea);
  if (selection) {
    selection.removeAllRanges();
    if (previousRange) selection.addRange(previousRange);
  }
  return ok;
}
