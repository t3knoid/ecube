import { beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { nextTick, reactive } from "vue";
import i18n from "@/i18n/index.js";
import LoginView from "@/views/LoginView.vue";

const mocks = vi.hoisted(() => ({
  route: { query: {} },
  push: vi.fn(),
  login: vi.fn(),
  changePassword: vi.fn(),
  getPublicAuthConfig: vi.fn(),
  theme: { currentLogo: null, currentLogoAlt: "Organization Logo" },
}));

vi.mock("vue-router", () => ({
  useRouter: () => ({ push: mocks.push }),
  useRoute: () => mocks.route,
}));

vi.mock("@/stores/auth.js", () => ({
  useAuthStore: () => ({
    login: mocks.login,
    changePassword: mocks.changePassword,
    isAuthenticated: false,
    passwordWarningDays: null,
  }),
}));

vi.mock("@/stores/theme.js", () => ({
  useThemeStore: () => reactive(mocks.theme),
}));

vi.mock("@/api/auth.js", () => ({
  getPublicAuthConfig: mocks.getPublicAuthConfig,
}));

describe("LoginView logo behavior", () => {
  beforeEach(() => {
    mocks.route.query = {};
    mocks.push.mockReset();
    mocks.login.mockReset();
    mocks.changePassword.mockReset();
    mocks.getPublicAuthConfig.mockReset();
    mocks.getPublicAuthConfig.mockResolvedValue({
      demo_mode_enabled: false,
      login_message: null,
      shared_password: null,
      demo_accounts: [],
      password_change_allowed: true,
    });
    mocks.theme.currentLogo = null;
    mocks.theme.currentLogoAlt = "Organization Logo";
  });

  it("renders the logo to the left of the app title when theme logo is available", () => {
    mocks.theme.currentLogo = "/themes/acme-logo.svg";
    mocks.theme.currentLogoAlt = "ACME Corp";

    const wrapper = mount(LoginView, { global: { plugins: [i18n] } });

    const logo = wrapper.find("img.login-logo-image");
    expect(logo.exists()).toBe(true);
    expect(logo.attributes("src")).toBe("/themes/acme-logo.svg");
    expect(logo.attributes("alt")).toBe("ACME Corp");
    expect(wrapper.find(".login-title").text()).toBe(i18n.global.t("app.name"));
  });

  it("renders text-only title when no theme logo is configured", () => {
    const wrapper = mount(LoginView, { global: { plugins: [i18n] } });

    expect(wrapper.find("img.login-logo-image").exists()).toBe(false);
    expect(wrapper.find(".login-title").text()).toBe(i18n.global.t("app.name"));
  });

  it("falls back to text-only title when logo image fails to load", async () => {
    mocks.theme.currentLogo = "/themes/broken-logo.svg";

    const wrapper = mount(LoginView, { global: { plugins: [i18n] } });
    await wrapper.find("img.login-logo-image").trigger("error");
    await nextTick();

    expect(wrapper.find("img.login-logo-image").exists()).toBe(false);
    expect(wrapper.find(".login-title").text()).toBe(i18n.global.t("app.name"));
  });

  it("keeps the demo guidance panel hidden when demo mode is disabled", async () => {
    const wrapper = mount(LoginView, { global: { plugins: [i18n] } });
    await flushPromises();

    expect(mocks.getPublicAuthConfig).toHaveBeenCalledTimes(1);
    expect(wrapper.find(".demo-login-panel").exists()).toBe(false);
  });

  it("renders public demo guidance when demo mode is enabled", async () => {
    mocks.getPublicAuthConfig.mockResolvedValue({
      demo_mode_enabled: true,
      login_message: "Use the shared demo accounts below.",
      shared_password: "Demo#123456",
      demo_accounts: [
        {
          username: "demo_manager",
          label: "Manager demo",
          description: "Review mounts, drives, and jobs.",
        },
      ],
      password_change_allowed: false,
    });

    const wrapper = mount(LoginView, { global: { plugins: [i18n] } });
    await flushPromises();

    const panel = wrapper.find(".demo-login-panel");
    expect(panel.exists()).toBe(true);
    expect(panel.text()).toContain("Use the shared demo accounts below.");
    expect(panel.text()).toContain("demo_manager");
    expect(panel.text()).toContain("Manager demo");
    expect(panel.text()).toContain("Review mounts, drives, and jobs.");
    expect(panel.text()).toContain(i18n.global.t("auth.demoSharedPassword"));
    expect(panel.text()).toContain("Demo#123456");

    const passwordInput = wrapper.find("#password");
    expect(passwordInput.element.value).toBe("Demo#123456");
  });

  it("shows an informational banner when setup redirects an already initialized system to login", async () => {
    mocks.route.query = { reason: "setup_already_initialized" };

    const wrapper = mount(LoginView, { global: { plugins: [i18n] } });
    await flushPromises();

    const banner = wrapper.find(".info-banner");
    expect(banner.exists()).toBe(true);
    expect(banner.text()).toContain(i18n.global.t("setup.alreadyInitializedTitle"));
    expect(banner.text()).toContain(i18n.global.t("setup.alreadyInitialized"));
  });

  it("opens the forced password change dialog when the backend reports an expired password", async () => {
    mocks.login.mockRejectedValue({
      response: {
        data: {
          reason: "password_expired",
          message: "Password expired",
        },
      },
    });
    mocks.changePassword.mockResolvedValue(undefined);

    const wrapper = mount(LoginView, { attachTo: document.body, global: { plugins: [i18n] } });
    await flushPromises();

    await wrapper.find('#username').setValue('operator1');
    await wrapper.find('#password').setValue('Old#123456');
    await wrapper.find('form').trigger('submit.prevent');
    await flushPromises();

    expect(document.body.textContent).toContain(i18n.global.t('auth.passwordExpiredTitle'));

    const dialogRoot = document.body;
    dialogRoot.querySelector('#password-change-new').value = 'New#123456789';
    dialogRoot.querySelector('#password-change-new').dispatchEvent(new Event('input'));
    dialogRoot.querySelector('#password-change-confirm').value = 'New#123456789';
    dialogRoot.querySelector('#password-change-confirm').dispatchEvent(new Event('input'));
    await nextTick();

    dialogRoot.querySelector('.dialog-actions .btn.btn-primary').click();
    await flushPromises();

    expect(mocks.changePassword).toHaveBeenCalledWith('operator1', 'Old#123456', 'New#123456789');
    expect(mocks.push).toHaveBeenCalledWith('/');
    wrapper.unmount();
  });

  it("does not open the forced password change dialog for demo accounts when password changes are disabled", async () => {
    mocks.getPublicAuthConfig.mockResolvedValue({
      demo_mode_enabled: true,
      login_message: "Demo mode",
      shared_password: "Demo#123456",
      demo_accounts: [
        {
          username: "demo_manager",
          label: "Manager demo",
          description: "Review mounts, drives, and jobs.",
        },
      ],
      password_change_allowed: false,
    });
    mocks.login.mockRejectedValue({
      response: {
        data: {
          reason: "password_expired",
          message: "Password expired",
        },
      },
    });

    const wrapper = mount(LoginView, { attachTo: document.body, global: { plugins: [i18n] } });
    await flushPromises();

    await wrapper.find('#username').setValue('demo_manager');
    await wrapper.find('form').trigger('submit.prevent');
    await flushPromises();

    expect(document.body.textContent).not.toContain(i18n.global.t('auth.passwordExpiredTitle'));
    expect(wrapper.text()).toContain(i18n.global.t('auth.demoPasswordManaged'));
    expect(mocks.changePassword).not.toHaveBeenCalled();
    wrapper.unmount();
  });
});
