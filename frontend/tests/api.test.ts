import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, BenchmarkApi } from "../src/api";

afterEach(() => vi.unstubAllGlobals());

describe("BenchmarkApi", () => {
  it("creates a match and keeps bearer tokens out of URLs", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          match_id: "m1",
          scenario_id: "basic-survival-v1",
          controller_tokens: { c1: "secret" },
          admin_token: "admin",
        }),
        { status: 201, headers: { "content-type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const created = await new BenchmarkApi("http://local").createMatch({
      scenario_id: "basic-survival-v1",
      seed: 17,
      colony_count: 1,
    });

    expect(created.match_id).toBe("m1");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://local/api/matches",
      expect.objectContaining({ method: "POST" }),
    );
    expect(JSON.stringify(fetchMock.mock.calls)).not.toContain("?token=");
  });

  it("sends controller credentials in Authorization for observation", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ turn: 4, colony_id: "c1" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await new BenchmarkApi("").observe("m1", "c1", "secret");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/matches/m1/observation?colony_id=c1",
      expect.objectContaining({ headers: { Authorization: "Bearer secret" } }),
    );
  });

  it("surfaces the server's structured error code", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ detail: { code: "stale_turn", message: "wrong turn" } }),
          { status: 409, headers: { "content-type": "application/json" } },
        ),
      ),
    );

    await expect(
      new BenchmarkApi("").submitActions("m1", "secret", {
        turn: 3,
        actions: [{ kind: "wait" }],
      }),
    ).rejects.toEqual(expect.objectContaining({ code: "stale_turn", status: 409 }));
  });
});
