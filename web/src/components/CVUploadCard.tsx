'use client'

import { useState } from 'react'

interface CVData {
  skills: string[]
  years_experience: number | null
  job_titles: string[]
  certifications: string[]
  languages: string[]
  education: string[]
  summary: string
  analyzed_at: string
}

interface CVUploadCardProps {
  onAnalysisComplete?: (data: CVData) => void
}

export default function CVUploadCard({ onAnalysisComplete }: CVUploadCardProps) {
  const [isDragging, setIsDragging] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [cvData, setCvData] = useState<CVData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [file, setFile] = useState<File | null>(null)

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }

  const handleDragLeave = () => {
    setIsDragging(false)
  }

  const validateFile = (f: File): string | null => {
    const maxSize = 10 * 1024 * 1024
    if (f.size > maxSize) {
      return 'File too large (max 10MB)'
    }

    const allowedTypes = ['application/pdf', 'text/plain']
    if (!allowedTypes.includes(f.type)) {
      return 'Unsupported file type. Use PDF or TXT.'
    }

    return null
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)

    const files = e.dataTransfer.files
    if (files.length > 0) {
      const f = files[0]
      const validationError = validateFile(f)
      if (validationError) {
        setError(validationError)
      } else {
        setFile(f)
        setError(null)
        uploadFile(f)
      }
    }
  }

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.currentTarget.files
    if (files && files.length > 0) {
      const f = files[0]
      const validationError = validateFile(f)
      if (validationError) {
        setError(validationError)
      } else {
        setFile(f)
        setError(null)
        uploadFile(f)
      }
    }
  }

  const uploadFile = async (f: File) => {
    setIsLoading(true)
    setError(null)

    try {
      const formData = new FormData()
      formData.append('file', f)

      const response = await fetch('/api/app/cv/upload', {
        method: 'POST',
        body: formData,
      })

      if (!response.ok) {
        const data = await response.json()
        throw new Error(data.error || 'Upload failed')
      }

      const result = await response.json()
      setCvData(result.analysis)
      onAnalysisComplete?.(result.analysis)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed')
      setFile(null)
    } finally {
      setIsLoading(false)
    }
  }

  const handleReset = () => {
    setCvData(null)
    setFile(null)
    setError(null)
  }

  if (cvData) {
    return (
      <div className="bg-white p-6 rounded-lg border border-gray-200">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-gray-900">CV Analyzed</h3>
          <button
            onClick={handleReset}
            className="text-sm text-blue-600 hover:text-blue-700 font-medium"
          >
            Upload New
          </button>
        </div>

        <div className="space-y-4">
          {/* Summary */}
          {cvData.summary && (
            <div>
              <h4 className="text-sm font-semibold text-gray-700 mb-1">Summary</h4>
              <p className="text-sm text-gray-600">{cvData.summary}</p>
            </div>
          )}

          {/* Skills */}
          {cvData.skills.length > 0 && (
            <div>
              <h4 className="text-sm font-semibold text-gray-700 mb-2">Skills</h4>
              <div className="flex flex-wrap gap-2">
                {cvData.skills.map((skill, i) => (
                  <span key={i} className="inline-flex items-center gap-1 px-3 py-1 bg-blue-50 text-blue-700 rounded-full text-xs font-medium">
                    {skill}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Experience */}
          {cvData.years_experience && (
            <div>
              <h4 className="text-sm font-semibold text-gray-700 mb-1">Experience</h4>
              <p className="text-sm text-gray-600">{cvData.years_experience} years</p>
            </div>
          )}

          {/* Job Titles */}
          {cvData.job_titles.length > 0 && (
            <div>
              <h4 className="text-sm font-semibold text-gray-700 mb-2">Recent Titles</h4>
              <ul className="text-sm text-gray-600 space-y-1">
                {cvData.job_titles.slice(0, 5).map((title, i) => (
                  <li key={i} className="flex items-center gap-2">
                    <span className="text-gray-400">•</span>
                    {title}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Certifications */}
          {cvData.certifications.length > 0 && (
            <div>
              <h4 className="text-sm font-semibold text-gray-700 mb-2">Certifications</h4>
              <ul className="text-sm text-gray-600 space-y-1">
                {cvData.certifications.map((cert, i) => (
                  <li key={i} className="flex items-center gap-2">
                    <span className="text-gray-400">•</span>
                    {cert}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Education */}
          {cvData.education.length > 0 && (
            <div>
              <h4 className="text-sm font-semibold text-gray-700 mb-2">Education</h4>
              <ul className="text-sm text-gray-600 space-y-1">
                {cvData.education.map((edu, i) => (
                  <li key={i} className="flex items-center gap-2">
                    <span className="text-gray-400">•</span>
                    {edu}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Languages */}
          {cvData.languages.length > 0 && (
            <div>
              <h4 className="text-sm font-semibold text-gray-700 mb-2">Languages</h4>
              <div className="flex flex-wrap gap-2">
                {cvData.languages.map((lang, i) => (
                  <span key={i} className="inline-flex items-center px-2.5 py-0.5 bg-gray-100 text-gray-800 rounded-full text-xs font-medium">
                    {lang}
                  </span>
                ))}
              </div>
            </div>
          )}

          <div className="pt-2 border-t border-gray-200">
            <p className="text-xs text-gray-500">
              Analyzed on {new Date(cvData.analyzed_at).toLocaleDateString()}
            </p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-white p-6 rounded-lg border border-gray-200">
      <h3 className="text-lg font-semibold text-gray-900 mb-2">Upload Your CV</h3>
      <p className="text-sm text-gray-600 mb-4">
        Extract your skills and experience to improve job matching. CV skills will help us match you with more relevant roles.
      </p>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg">
          <p className="text-sm text-red-800">{error}</p>
        </div>
      )}

      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={`relative border-2 border-dashed rounded-lg p-8 text-center transition-colors ${
          isDragging ? 'border-blue-400 bg-blue-50' : 'border-gray-300 hover:border-gray-400'
        } ${isLoading ? 'opacity-50 pointer-events-none' : ''}`}
      >
        {isLoading ? (
          <div className="space-y-2">
            <div className="animate-spin mx-auto h-8 w-8 border-4 border-blue-200 border-t-blue-600 rounded-full"></div>
            <p className="text-sm text-gray-600">Analyzing your CV...</p>
          </div>
        ) : (
          <>
            <svg className="mx-auto h-12 w-12 text-gray-400 mb-2" stroke="currentColor" fill="none" viewBox="0 0 48 48">
              <path d="M28 8H12a4 4 0 00-4 4v24a4 4 0 004 4h24a4 4 0 004-4V20m-6-10v10m-6-6h12M8 36h32" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <p className="text-sm font-medium text-gray-900 mb-1">Drop your CV here or click to select</p>
            <p className="text-xs text-gray-500 mb-4">PDF or TXT (max 10MB)</p>
            <input
              type="file"
              accept=".pdf,.txt,application/pdf,text/plain"
              onChange={handleFileSelect}
              className="hidden"
              id="cv-file-input"
              disabled={isLoading}
            />
            <label
              htmlFor="cv-file-input"
              className="inline-block px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 cursor-pointer transition-colors"
            >
              Choose File
            </label>
          </>
        )}
      </div>

      {file && !isLoading && !cvData && (
        <div className="mt-4 p-3 bg-blue-50 rounded-lg">
          <p className="text-sm text-blue-800 font-medium">{file.name}</p>
        </div>
      )}
    </div>
  )
}
