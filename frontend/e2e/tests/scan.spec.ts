// Step 13g: on a phone, Records photographs a paper document page by page,
// checks the pages, removes one, and saves them as one PDF on the case.
// Runs as a phone (touch screen, mobile browser): "Scan with camera" only
// shows on touch screens. The photos are real PNGs made here.
import { deflateSync } from "node:zlib";

import { devices, expect, test } from "@playwright/test";

import { loginAs } from "./helpers";

function crc32(bytes: Buffer): number {
  let crc = ~0;
  for (const byte of bytes) {
    crc ^= byte;
    for (let k = 0; k < 8; k++) crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
  }
  return ~crc >>> 0;
}

/** A plain PNG "photo" of a page: grey, with a dark band down its left side. */
function pagePhoto(width: number, height: number): Buffer {
  const chunk = (kind: string, data: Buffer) => {
    const body = Buffer.concat([Buffer.from(kind), data]);
    const out = Buffer.alloc(12 + data.length);
    out.writeUInt32BE(data.length, 0);
    body.copy(out, 4);
    out.writeUInt32BE(crc32(body), 8 + data.length);
    return out;
  };
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header.set([8, 2, 0, 0, 0], 8); // 8-bit RGB
  const rows = [];
  for (let y = 0; y < height; y++) {
    const row = Buffer.alloc(1 + width * 3, 220);
    row[0] = 0; // no filter
    row.fill(30, 1, 1 + Math.floor(width / 10) * 3);
    rows.push(row);
  }
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", header),
    chunk("IDAT", deflateSync(Buffer.concat(rows))),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

test("Records scans a document with a phone: two pages taken, one removed, saved as one PDF", async ({ browser }) => {
  const phone = devices["Pixel 7"];
  const records = await loginAs(browser, "records@motie.test", {
    viewport: phone.viewport, userAgent: phone.userAgent, deviceScaleFactor: phone.deviceScaleFactor, isMobile: true, hasTouch: true,
  });
  // A case waiting for Records (the demo seed's "Submitted").
  await records.goto("/staff");
  await records.getByRole("link", { name: /FL\/\d{4}\/\d{4}/ }).first().click();
  await expect(records.getByText("Scan with camera").first()).toBeVisible();
  // The camera itself is a file box: on a real phone it opens the rear camera.
  const camera = records.getByLabel("Photo for Invoice");

  await camera.setInputFiles({ name: "page1.png", mimeType: "image/png", buffer: pagePhoto(600, 800) });
  await expect(records.getByRole("img", { name: "Page 1" })).toBeVisible();
  await camera.setInputFiles({ name: "page2.png", mimeType: "image/png", buffer: pagePhoto(800, 600) });
  await expect(records.getByRole("img", { name: "Page 2" })).toBeVisible();

  // Page 1 was a mistake: remove it; page 2 becomes page 1.
  await records.getByRole("button", { name: "Remove 1" }).click();
  await expect(records.getByRole("img", { name: "Page 2" })).toHaveCount(0);
  await expect(records.getByRole("img", { name: "Page 1" })).toBeVisible();

  await records.getByRole("button", { name: "Save 1 page as one PDF" }).click();
  await expect(records.getByText("Scanned and saved as one PDF.")).toBeVisible();
});

test("on a computer, there's no camera option", async ({ browser }) => {
  const records = await loginAs(browser, "records@motie.test");
  await records.goto("/staff");
  await records.getByRole("link", { name: /FL\/\d{4}\/\d{4}/ }).first().click();
  await expect(records.getByText("Scan with camera").first()).toBeHidden();
});
