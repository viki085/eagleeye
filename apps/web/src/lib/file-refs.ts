/**
 * Dragging a file from the right panel into the message box inserts "[file name]". The server
 * matches the name to the user's files (apps' agents/references.py), so the token must use the
 * same names it recognises: the file name, plus "(sheet)" for a workbook sheet.
 */

export const FILE_REF_MIME = "application/x-eagleeye-file";

export function datasetToken(d: { filename: string; sheet: string }): string {
  return d.sheet ? `[${d.filename} (${d.sheet})]` : `[${d.filename}]`;
}

export function documentToken(d: { filename: string }): string {
  return `[${d.filename}]`;
}

/**
 * Inserts the token at the caret with a space on either side where needed. Returns the new text
 * and where the caret should go (just after the token and its trailing space).
 */
export function insertToken(text: string, caret: number, token: string): { text: string; caret: number } {
  const at = Math.max(0, Math.min(caret, text.length));
  const before = text.slice(0, at);
  const after = text.slice(at);
  const lead = before && !/\s$/.test(before) ? " " : "";
  const trail = after.startsWith(" ") ? "" : " ";
  const inserted = `${lead}${token}${trail}`;
  // the caret lands after the space that follows the token, ready to keep typing
  return { text: before + inserted + after, caret: at + inserted.length + (trail ? 0 : 1) };
}
