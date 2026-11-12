export function apiOrigin(base?: string): string;
export function policy(hashes: Iterable<string>, api: string): string;
export function inlineHashes(html: string): Set<string>;
export function addCsp(html: string, api: string): string;
