import { describe, expect, it } from "vitest";
import { judge, type Payment } from "../src/reconcile";

const USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913";
const TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef";
const PAY_TO = "0xebA22e8CD05Cb72A2F913099D6cCA666DD6D35B0";
const pad = (a: string) => "0x" + a.toLowerCase().slice(2).padStart(64, "0");

const p: Payment = { source: "sale", id: 1, network: "eip155:8453", tx: "0xabc", pay_to: PAY_TO, amount_micro: 5000, created_at: 0 };
const log = (to: string, amount: number, address = USDC) => ({
  address,
  topics: [TRANSFER, pad("0x1111111111111111111111111111111111111111"), pad(to)],
  data: "0x" + amount.toString(16).padStart(64, "0"),
});

describe("payment reconciliation", () => {
  it("confirms a successful USDC transfer of the right amount to the right wallet", () => {
    expect(judge(p, { status: "0x1", logs: [log(PAY_TO, 5000)] })).toBe("confirmed");
  });
  it("flags a missing, reverted or wrong transfer", () => {
    expect(judge(p, null)).toBe("not_found");
    expect(judge(p, { status: "0x0", logs: [log(PAY_TO, 5000)] })).toBe("failed");
    expect(judge(p, { status: "0x1", logs: [log(PAY_TO, 4999)] })).toBe("wrong_transfer");
    expect(judge(p, { status: "0x1", logs: [log("0x2222222222222222222222222222222222222222", 5000)] })).toBe("wrong_transfer");
    expect(judge(p, { status: "0x1", logs: [log(PAY_TO, 5000, "0x3333333333333333333333333333333333333333")] })).toBe("wrong_transfer");
  });
  it("knows Base Sepolia's USDC and refuses unknown networks", () => {
    const t = { ...p, network: "eip155:84532" };
    expect(judge(t, { status: "0x1", logs: [log(PAY_TO, 5000, "0x036cbd53842c5426634e7929541ec2318f3dcf7e")] })).toBe("confirmed");
    expect(judge({ ...p, network: "eip155:1" }, { status: "0x1", logs: [] })).toBe("unknown_network");
  });
});
