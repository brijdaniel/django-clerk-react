import React, { useCallback, useState, useRef } from 'react'
import clsx from 'clsx'
import { CloudArrowUpIcon, DocumentIcon, XMarkIcon } from '@heroicons/react/24/outline'

interface FileUploadProps {
	onFileSelect: (file: File) => void
	accept?: string
	className?: string
	disabled?: boolean
	multiple?: boolean
	sheetName?: string
	onFileRemove?: () => void
	maxSize?: number // in bytes
}

export function FileUpload({ 
	onFileSelect, 
	accept = '.xlsx,.xls', 
	className,
	disabled = false,
	multiple = false,
	sheetName,
	onFileRemove,
	maxSize = 5 * 1024 * 1024 // 5MB default
}: FileUploadProps) {
	const [isDragOver, setIsDragOver] = useState(false)
	const [selectedFile, setSelectedFile] = useState<File | null>(null)
	const [error, setError] = useState<string | null>(null)
	const inputRef = useRef<HTMLInputElement>(null)

	// Helper functions to determine file type context
	const isImageUpload = accept.includes('.png') || accept.includes('.jpg') || accept.includes('.jpeg') || accept.includes('.gif')
	const isExcelUpload = accept.includes('.xlsx') || accept.includes('.xls')
	
	const getFileTypeLabel = () => {
		if (isImageUpload) return 'image'
		if (isExcelUpload) return 'Excel file'
		return 'file'
	}
	
	const getAcceptLabel = () => {
		if (isImageUpload) return '(.png, .jpg, .jpeg, .gif files)'
		if (isExcelUpload) return '(.xlsx, .xls files)'
		return `(${accept} files)`
	}
	
	const validateFile = useCallback((file: File): string | null => {
		if (file.size > maxSize) {
			const maxSizeMB = (maxSize / 1024 / 1024).toFixed(1)
			return `File size must be less than ${maxSizeMB} MB`
		}
		return null
	}, [maxSize])

	const handleDragOver = useCallback((e: React.DragEvent) => {
		e.preventDefault()
		if (!disabled) {
			setIsDragOver(true)
		}
	}, [disabled])

	const handleDragLeave = useCallback((e: React.DragEvent) => {
		e.preventDefault()
		setIsDragOver(false)
	}, [])

	const handleDrop = useCallback((e: React.DragEvent) => {
		e.preventDefault()
		setIsDragOver(false)
		
		if (disabled) return

		const files = Array.from(e.dataTransfer.files)
		if (files.length > 0) {
			const file = files[0]
			console.log('FileUpload: File dropped', { fileName: file.name, fileSize: file.size })
			
			const validationError = validateFile(file)
			if (validationError) {
				setError(validationError)
				setSelectedFile(null)
				return
			}
			
			setError(null)
			setSelectedFile(file)
			onFileSelect(file)
		}
	}, [disabled, onFileSelect, validateFile])

	const handleFileInput = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
		const files = e.target.files
		if (files && files.length > 0) {
			const file = files[0]
			console.log('FileUpload: File selected via input', { fileName: file.name, fileSize: file.size })
			
			const validationError = validateFile(file)
			if (validationError) {
				setError(validationError)
				setSelectedFile(null)
				// Clear the input value
				if (inputRef.current) {
					inputRef.current.value = ''
				}
				return
			}
			
			setError(null)
			setSelectedFile(file)
			onFileSelect(file)
		}
	}, [onFileSelect, validateFile])

	const handleRemoveFile = useCallback((e: React.MouseEvent) => {
		e.preventDefault()
		e.stopPropagation()
		console.log('FileUpload: Removing file', { fileName: selectedFile?.name })
		setSelectedFile(null)
		setError(null)
		// Clear the input value to ensure subsequent file selections work
		if (inputRef.current) {
			inputRef.current.value = ''
		}
		onFileRemove?.()
	}, [onFileRemove, selectedFile?.name])

	const inputId = React.useId()

	return (
		<div className={clsx('relative', className)}>
			<input
				ref={inputRef}
				id={inputId}
				type="file"
				accept={accept}
				onChange={handleFileInput}
				disabled={disabled}
				multiple={multiple}
				className="sr-only"
			/>
			
			<label
				htmlFor={inputId}
				className={clsx(
					'relative block w-full rounded-lg border-2 border-dashed px-3 py-3 text-center transition-colors cursor-pointer',
					{
						'border-gray-300 dark:border-gray-600 hover:border-gray-400 dark:hover:border-gray-500': !isDragOver && !disabled && !selectedFile,
						'border-blue-400 dark:border-blue-500 bg-blue-50 dark:bg-blue-950/20': isDragOver && !disabled,
						'border-green-400 dark:border-green-500 bg-green-50 dark:bg-green-950/20': selectedFile && !disabled,
						'border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50 cursor-not-allowed': disabled,
					}
				)}
				onDragOver={handleDragOver}
				onDragLeave={handleDragLeave}
				onDrop={handleDrop}
			>
				{selectedFile ? (
					<div className="flex items-center justify-center space-x-2">
						<DocumentIcon className="h-10 w-10 text-green-500" />
						<div className="flex-1 text-left">
							<p className="text-sm font-medium text-gray-900 dark:text-white">
								{selectedFile.name}{sheetName ? ` • Sheet: ${sheetName}` : ''}
							</p>
							<p className="text-xs text-gray-500 dark:text-gray-400">
								{(selectedFile.size / 1024 / 1024).toFixed(2)} MB
							</p>
						</div>
						<button
							type="button"
							onClick={handleRemoveFile}
							className="flex-shrink-0 p-1 rounded-full text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 transition-colors"
						>
							<XMarkIcon className="h-5 w-5" />
						</button>
					</div>
				) : (
					<div className="flex items-center space-x-2">
						<CloudArrowUpIcon 
							className={clsx(
								'h-10 w-10 flex-shrink-0',
								{
									'text-gray-500 dark:text-gray-400': !isDragOver && !disabled,
									'text-blue-600 dark:text-blue-400': isDragOver && !disabled,
									'text-gray-300 dark:text-gray-600': disabled,
								}
							)} 
						/>
						<div className="flex-1">
							<p className={clsx(
								'text-sm font-medium',
								{
									'text-gray-900 dark:text-white': !disabled,
									'text-gray-500 dark:text-gray-400': disabled,
								}
							)}>
								{isDragOver ? `Drop your ${getFileTypeLabel()} here` : `Upload ${getFileTypeLabel()}`}
							</p>
							<p className={clsx(
								'text-xs text-gray-500 dark:text-gray-400'
							)}>
								Drag and drop or click to browse {getAcceptLabel()}
							</p>
						</div>
					</div>
				)}
			</label>
			
			{/* Error message */}
			{error && (
				<div className="mt-2 p-2 bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-800 rounded-lg">
					<p className="text-sm text-red-600 dark:text-red-400">
						{error}
					</p>
				</div>
			)}
		</div>
	)
}