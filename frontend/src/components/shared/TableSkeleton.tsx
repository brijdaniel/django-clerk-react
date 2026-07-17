import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../ui/table';

interface TableSkeletonProps {
	columns: string[];
	rows?: number;
	showPagination?: boolean;
}

function SkeletonBox({ className }: { className?: string }) {
	return (
		<div 
			className={`animate-pulse bg-gray-200 dark:bg-gray-700 rounded ${className || 'h-3 w-full'}`}
		/>
	);
}

export default function TableSkeleton({ 
	columns, 
	rows = 3, 
	showPagination = false 
}: TableSkeletonProps) {
	return (
		<div className="h-full flex flex-col">
			{/* Pagination Skeleton - Top */}
			{showPagination && (
				<div className="px-2 py-2 border-b border-zinc-950/10 dark:border-white/10 mb-2 flex-shrink-0">
					<div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 mb-1">
						<div className="flex-shrink-0">
							<SkeletonBox className="h-4 w-32" />
						</div>
						<div className="flex items-center space-x-1 flex-wrap gap-1">
							<SkeletonBox className="h-6 w-16" />
							<SkeletonBox className="h-6 w-6" />
							<SkeletonBox className="h-6 w-6" />
							<SkeletonBox className="h-6 w-6" />
							<SkeletonBox className="h-6 w-12" />
							<SkeletonBox className="h-6 w-8" />
						</div>
					</div>
				</div>
			)}

			{/* Table Skeleton */}
			<div className="flex-1 min-h-0 overflow-auto">
				<Table className="w-full table-fixed">
					<TableHead>
						<TableRow>
							{columns.map((_column, index) => (
								<TableHeader key={index}>
									<SkeletonBox className="h-3 w-2/3" />
								</TableHeader>
							))}
						</TableRow>
					</TableHead>
					<TableBody>
						{Array.from({ length: rows }, (_, rowIndex) => (
							<TableRow key={rowIndex}>
								{columns.map((_, colIndex) => (
									<TableCell key={colIndex}>
										<SkeletonBox className={`h-3 ${
											colIndex === 0 ? 'w-4/5' : 
											colIndex === columns.length - 1 ? 'w-12' : 
											'w-3/4'
										}`} />
									</TableCell>
								))}
							</TableRow>
						))}
					</TableBody>
				</Table>
			</div>
		</div>
	);
}