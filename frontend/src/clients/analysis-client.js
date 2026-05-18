"use client";

import { createHttpAnalysisClient } from "./http-analysis-client";
import { createLocalAnalysisClient } from "./local-analysis-client";

const mode = process.env.NEXT_PUBLIC_ANALYSIS_CLIENT_MODE ?? "http";

export const analysisClient =
  mode === "local" ? createLocalAnalysisClient() : createHttpAnalysisClient();
