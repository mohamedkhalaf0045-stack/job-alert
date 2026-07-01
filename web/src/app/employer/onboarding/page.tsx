'use client'

import OnboardingChatbot from '@/components/OnboardingChatbot'

export default function EmployerOnboardingPage() {
  return (
    <div className="min-h-screen bg-gray-50 flex flex-col items-center justify-start px-4 py-12">
      <div className="w-full max-w-lg">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-gray-900">Set up your company profile</h1>
          <p className="text-gray-500 text-sm mt-1">Answer a few quick questions to get started</p>
        </div>
        <OnboardingChatbot profileType="employer" />
      </div>
    </div>
  )
}
