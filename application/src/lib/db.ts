import { neon } from '@neondatabase/serverless';

// Strip channel_binding — not supported by the HTTP driver
const url = (process.env.NEON_DATABASE_URL ?? '').replace('&channel_binding=require', '');
export const sql = neon(url);
