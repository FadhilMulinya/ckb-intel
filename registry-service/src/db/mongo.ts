import mongoose from "mongoose";
import { environments } from "../environments.js";

let connected = false;

export async function connectMongo(): Promise<typeof mongoose> {
  if (connected) return mongoose;
  if (!environments.mongodbUri) throw new Error("MONGODB_URI is required (external MongoDB/Atlas)");
  await mongoose.connect(environments.mongodbUri, { serverSelectionTimeoutMS: 5000, connectTimeoutMS: 5000, socketTimeoutMS: 10000, maxPoolSize: 5 });
  connected = true;
  console.log("[mongo] connected");
  return mongoose;
}

export async function disconnectMongo(): Promise<void> {
  if (!connected) return;
  await mongoose.disconnect();
  connected = false;
}
