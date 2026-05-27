import { neon } from '@neondatabase/serverless';

type NeonClient = ReturnType<typeof neon>;

function cleanDatabaseUrl(value: string | undefined) {
  return (value ?? '')
    .trim()
    .replace(/^['"]|['"]$/g, '')
    .replace('&channel_binding=require', '');
}

let client: NeonClient | null = null;

function getSql() {
  if (client) return client;

  // Strip channel_binding because the Neon HTTP driver does not support it.
  const url = cleanDatabaseUrl(process.env.NEON_DATABASE_URL || process.env.DATABASE_URL);
  if (!url) {
    throw new Error('NEON_DATABASE_URL or DATABASE_URL is required for dashboard API requests.');
  }

  client = neon(url);
  return client;
}

export const sql: any = (strings: TemplateStringsArray, ...values: any[]) => getSql()(strings, ...values);
