'use client'

import { ChevronDown } from 'lucide-react'

const errorText = '该字段不完整。'

function FieldShell({
  label,
  value,
  children,
  focused = false,
  invalid = false,
}: {
  label: string
  value?: string
  children?: React.ReactNode
  focused?: boolean
  invalid?: boolean
}) {
  return (
    <div>
      <div
        className={[
          'flex min-h-[72px] w-full flex-col justify-center rounded-[16px] border px-4 transition-colors',
          focused
            ? 'border-black bg-[#f8f8f8]'
            : invalid
              ? 'border-red-100 bg-[#f8f8f8]'
              : 'border-transparent bg-[#f8f8f8]',
        ].join(' ')}
      >
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[14px] font-semibold leading-5 text-slate-500">{label}</p>
            {value && <p className="mt-0.5 truncate text-[14px] leading-5 text-slate-950">{value}</p>}
          </div>
          {children}
        </div>
      </div>
      {invalid && <p className="mt-1.5 text-[14px] font-semibold leading-5 text-red-600">{errorText}</p>}
    </div>
  )
}

export default function BillingAddressPage() {
  return (
    <div className="min-h-screen bg-white px-6 py-10 text-slate-950 sm:px-8">
      <section className="mx-auto w-full max-w-[488px]">
        <h1 className="mb-4 px-2 text-[18px] font-medium leading-7 text-slate-950">账单地址</h1>

        <form className="space-y-3" aria-label="账单地址">
          <FieldShell label="全名" value="KANG" />

          <FieldShell label="国家或地区" value="美国">
            <ChevronDown className="h-5 w-5 shrink-0 text-slate-600" aria-hidden="true" />
          </FieldShell>

          <FieldShell label="地址第 1 行" focused invalid />

          <FieldShell label="地址第 2 行" />

          <FieldShell label="城市" invalid />

          <div className="grid grid-cols-2 gap-2">
            <FieldShell label="州" invalid>
              <ChevronDown className="h-5 w-5 shrink-0 text-slate-600" aria-hidden="true" />
            </FieldShell>

            <FieldShell label="邮政编码" invalid />
          </div>
        </form>
      </section>
    </div>
  )
}
