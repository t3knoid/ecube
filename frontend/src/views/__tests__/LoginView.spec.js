import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick, reactive } from 'vue'
import i18n from '@/i18n/index.js'
import LoginView from '@/views/LoginView.vue'

const mocks = vi.hoisted(() => ({
  route: { query: {} },
  push: vi.fn(),
  login: vi.fn(),
  theme: { currentLogo: null, currentLogoAlt: 'Organization Logo' },
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: mocks.push }),
  useRoute: () => mocks.route,
}))

vi.mock('@/stores/auth.js', () => ({
  useAuthStore: () => ({ login: mocks.login }),
}))

vi.mock('@/stores/theme.js', () => ({
  useThemeStore: () => reactive(mocks.theme),
}))

describe('LoginView logo behavior', () => {
  beforeEach(() => {
    mocks.route.query = {}
    mocks.push.mockReset()
    mocks.login.mockReset()
    mocks.theme.currentLogo = null
    mocks.theme.currentLogoAlt = 'Organization Logo'
  })

  it('renders the logo to the left of the app title when theme logo is available', () => {
    mocks.theme.currentLogo = '/themes/acme-logo.svg'
    mocks.theme.currentLogoAlt = 'ACME Corp'

    const wrapper = mount(LoginView, { global: { plugins: [i18n] } })

    const logo = wrapper.find('img.login-logo-image')
    expect(logo.exists()).toBe(true)
    expect(logo.attributes('src')).toBe('/themes/acme-logo.svg')
    expect(logo.attributes('alt')).toBe('ACME Corp')
    expect(wrapper.find('.login-title').text()).toBe(i18n.global.t('app.name'))
  })

  it('renders text-only title when no theme logo is configured', () => {
    const wrapper = mount(LoginView, { global: { plugins: [i18n] } })

    expect(wrapper.find('img.login-logo-image').exists()).toBe(false)
    expect(wrapper.find('.login-title').text()).toBe(i18n.global.t('app.name'))
  })

  it('falls back to text-only title when logo image fails to load', async () => {
    mocks.theme.currentLogo = '/themes/broken-logo.svg'

    const wrapper = mount(LoginView, { global: { plugins: [i18n] } })
    await wrapper.find('img.login-logo-image').trigger('error')
    await nextTick()

    expect(wrapper.find('img.login-logo-image').exists()).toBe(false)
    expect(wrapper.find('.login-title').text()).toBe(i18n.global.t('app.name'))
  })
})
