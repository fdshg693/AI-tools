import process from "node:process";
import { LinearClient } from "@linear/sdk";
import { missingRequiredKeyMessage } from "./env.mjs";

export function createClient() {
  const apiKey = process.env.LINEAR_API_KEY;
  if (!apiKey) {
    throw new Error(missingRequiredKeyMessage("LINEAR_API_KEY"));
  }
  return new LinearClient({ apiKey });
}
