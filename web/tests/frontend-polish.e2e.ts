import { test } from "@e2e-dev/web";
import { expect } from "e2e";

for (const viewport of [{ width: 1440, height: 900 }, { width: 768, height: 900 }, { width: 390, height: 844 }]) {
  test(`login isolated session remains readable at ${viewport.width} pixels`, async ({ app, browser, screen }) => {
    await browser.setViewport(viewport);
    await browser.route("**/api/v1/admin/session", (route) => route.request.method === "POST"
      ? route.fulfill({ status: 401, json: { detail: "Invalid administrator password" } })
      : route.fulfill({ json: { authenticated: false, configured: true } }));
    await app.open("/admin.html?view=library");
    await expect(screen.getByRole("heading", "后台登录", { exact: true })).toBeVisible();
    await browser.evaluate(async () => { await document.fonts.ready; return null; });
    await expect(browser.locator(".admin-entry-illustration")).toBeVisible();
    const layout = await browser.evaluate(async () => {
      const illustration = document.querySelector<HTMLImageElement>(".admin-entry-illustration");
      await illustration?.decode();
      const form = document.querySelector(".admin-entry-content form")?.getBoundingClientRect();
      const submit = document.querySelector(".admin-entry-submit")?.getBoundingClientRect();
      return {
        illustrationLoaded: illustration instanceof HTMLImageElement && illustration.naturalWidth > 0,
        formWidth: form?.width ?? 0,
        actionVisible: submit !== undefined && submit.top >= 0 && submit.bottom <= window.innerHeight,
      };
    });
    expect(layout.illustrationLoaded).toBe(true);
    expect(layout.formWidth > 0 && layout.formWidth <= 420).toBe(true);
    expect(layout.actionVisible).toBe(true);
    expect(await browser.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await app.screenshot(`login-${viewport.width}`);
    await screen.getByLabel("管理员密码", { exact: true }).fill("isolated-invalid-password");
    await screen.getByRole("button", "显示密码", { exact: true }).tap();
    await expect(screen.getByRole("button", "隐藏密码", { exact: true })).toBeVisible();
    await screen.getByRole("button", "隐藏密码", { exact: true }).tap();
    await expect(screen.getByRole("button", "显示密码", { exact: true })).toBeVisible();
    await screen.getByRole("button", "登录", { exact: true }).tap();
    await expect(screen.getByRole("alert")).toContainText("密码不正确");
    await app.screenshot(`login-error-${viewport.width}`);
  });
}
