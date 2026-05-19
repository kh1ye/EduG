'use client'

import { Copy } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import rehypeKatex from 'rehype-katex'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import { visit } from 'unist-util-visit'
import { MermaidInText } from '@/components/visualization/MermaidDiagram'
import { processLatexInMarkdown } from '@/lib/latex-processor'
import 'katex/dist/katex.min.css'

const katexOptions = {
  throwOnError: false,
  errorColor: '#b91c1c',
  strict: false,
  trust: false,
  macros: {
    '\\xrightarrow': '\\xrightarrow',
    '\\Delta': '\\Delta',
    '\\text': '\\text'
  }
}

function remarkUnwrapCodeBlocks() {
  return (tree: any) => {
    visit(tree, 'element', (node, index, parent) => {
      if (
        node.tagName === 'p' &&
        node.children &&
        node.children.length === 1 &&
        node.children[0].type === 'element' &&
        node.children[0].tagName === 'pre'
      ) {
        if (parent && typeof index === 'number') {
          parent.children[index] = node.children[0]
        }
      }
    })
  }
}

function normalizeTutorMarkdown(content: string, isStreaming: boolean): string {
  let text = processLatexInMarkdown(content, isStreaming).replace(/\r\n/g, '\n')

  // Models often emit "##标题" without the required Markdown space.
  text = text.replace(/(^|\n)(#{1,6})([^\s#])/g, '$1$2 $3')

  // Add paragraph breaks before headings that were streamed inline.
  text = text.replace(/([。！？.!?])\s*(#{2,6}\s+)/g, '$1\n\n$2')

  // Make common inline bullet patterns readable when the model forgets line breaks.
  text = text.replace(/([。！？.!?])\s*(-\s*[\u4e00-\u9fa5A-Za-z0-9])/g, '$1\n$2')
  text = text.replace(/([。！？.!?])\s*(\d+\.\s+)/g, '$1\n$2')

  // Repair compact GFM table separators such as "...|B||---|---|..."
  text = text.replace(/\|\s*\|\s*(-{3,})/g, '|\n|$1')
  text = text.replace(/(\|[-: ]+\|[-|: ]+)([^\n])/g, '$1\n$2')

  return text.trim()
}

interface MarkdownContentProps {
  content: string
  isStreaming?: boolean
  compact?: boolean
}

export function MarkdownContent({
  content,
  isStreaming = false,
  compact = false
}: MarkdownContentProps) {
  const normalized = normalizeTutorMarkdown(content, isStreaming)

  return (
    <div className={compact ? 'text-[15px] leading-7 text-gray-800' : 'text-[15px] leading-7 text-gray-800'}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath, remarkUnwrapCodeBlocks]}
        rehypePlugins={[[rehypeKatex, katexOptions]]}
        components={{
          h1: ({ children }) => (
            <h1 className="mb-4 mt-1 text-2xl font-semibold leading-tight text-gray-950">
              {children}
            </h1>
          ),
          h2: ({ children }) => (
            <h2 className="mb-3 mt-6 text-xl font-semibold leading-tight text-gray-950 first:mt-0">
              {children}
            </h2>
          ),
          h3: ({ children }) => (
            <h3 className="mb-2 mt-5 text-base font-semibold leading-snug text-gray-950">
              {children}
            </h3>
          ),
          p: ({ children }) => (
            <p className="my-3 break-words text-gray-800 first:mt-0 last:mb-0">
              {children}
            </p>
          ),
          strong: ({ children }) => (
            <strong className="font-semibold text-gray-950">{children}</strong>
          ),
          ul: ({ children }) => (
            <ul className="my-3 space-y-2 pl-5 list-disc marker:text-gray-400">
              {children}
            </ul>
          ),
          ol: ({ children }) => (
            <ol className="my-3 space-y-2 pl-5 list-decimal marker:text-gray-500">
              {children}
            </ol>
          ),
          li: ({ children }) => (
            <li className="pl-1 leading-7 text-gray-800">{children}</li>
          ),
          blockquote: ({ children }) => (
            <blockquote className="my-4 border-l-4 border-gray-300 bg-gray-50 px-4 py-2 text-gray-700">
              {children}
            </blockquote>
          ),
          code(props: any) {
            const { inline, className, children, ...rest } = props
            const match = /language-mermaid/.exec(className || '')
            if (!inline && match) {
              const code = String(children).replace(/\n$/, '')
              return <MermaidInText text={`\`\`\`mermaid\n${code}\n\`\`\``} />
            }

            if (!inline) {
              const code = String(children).replace(/\n$/, '')
              return (
                <div className="group relative my-5">
                  <div className="absolute right-3 top-3 z-10">
                    <button
                      onClick={() => navigator.clipboard.writeText(code)}
                      className="opacity-0 group-hover:opacity-100 transition-opacity bg-gray-800 hover:bg-gray-700 text-gray-200 p-2 rounded-md shadow-sm"
                      title="复制代码"
                    >
                      <Copy className="h-4 w-4" />
                    </button>
                  </div>
                  <div className="overflow-hidden rounded-lg border border-gray-800 bg-gray-900 shadow-sm">
                    <div className="flex items-center justify-between border-b border-gray-700 bg-gray-800 px-4 py-2">
                      <span className="font-mono text-xs font-medium text-gray-300">
                        {className?.replace('language-', '') || 'code'}
                      </span>
                    </div>
                    <pre className="overflow-x-auto p-4">
                      <code className={`font-mono text-sm text-gray-100 ${className || ''}`} {...rest}>
                        {children}
                      </code>
                    </pre>
                  </div>
                </div>
              )
            }

            return (
              <code className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-[13px] text-gray-800" {...rest}>
                {children}
              </code>
            )
          },
          table: ({ children }) => (
            <div className="my-5 overflow-x-auto rounded-lg border border-gray-200">
              <table className="min-w-full divide-y divide-gray-200">{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead className="bg-gray-50">{children}</thead>,
          tbody: ({ children }) => <tbody className="divide-y divide-gray-100 bg-white">{children}</tbody>,
          tr: ({ children }) => <tr className="align-top">{children}</tr>,
          th: ({ children }) => (
            <th className="px-4 py-3 text-left text-xs font-semibold text-gray-700">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="px-4 py-3 text-sm leading-6 text-gray-700">{children}</td>
          ),
          a: ({ children, href }) => (
            <a
              href={href}
              className="font-medium text-blue-600 hover:text-blue-700 hover:underline"
              target="_blank"
              rel="noopener noreferrer"
            >
              {children}
            </a>
          )
        }}
      >
        {normalized}
      </ReactMarkdown>
    </div>
  )
}
