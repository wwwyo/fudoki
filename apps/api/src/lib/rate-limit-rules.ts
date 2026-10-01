export const rateLimitRules = {
  anonymous: { limit: 60, period: 60 },
  authenticated: { limit: 600, period: 60 },
} as const
