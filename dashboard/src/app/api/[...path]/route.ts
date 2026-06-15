import { NextRequest, NextResponse } from "next/server";

const BACKEND = "http://localhost:8420";

export async function GET(req: NextRequest) {
  const path = req.nextUrl.pathname.replace("/api", "");
  const res = await fetch(`${BACKEND}${path}${req.nextUrl.search}`);
  const data = await res.json();
  return NextResponse.json(data);
}
