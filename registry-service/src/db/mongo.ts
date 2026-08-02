import mongoose from "mongoose";
import { config } from "../config/index.js";

let connected = false;

export async function connectMongo(): Promise<typeof mongoose> {
  if (connected) return mongoose;
  await mongoose.connect(config.mongodbUri);
  connected = true;
  console.log(`[mongo] connected ✅ -> ${config.mongodbUri}`);
  return mongoose;
}

export async function disconnectMongo(): Promise<void> {
  if (!connected) return;
  await mongoose.disconnect();
  connected = false;
}
