import dayjs from 'dayjs';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../ui/table';
import { StatusBadge } from './StatusBadge';
import type { Schedule } from '../types/schedule.types';
import Logger from '../utils/logger';
import { ScheduleDetails } from './ScheduleDetails';
import React, { useState } from 'react';
import { ChevronDownIcon, ChevronRightIcon } from '@heroicons/react/16/solid';

export default function ScheduleTable({
	messages,
	selectedMessageId,
	setSelectedMessageId,
}: {
	messages: Schedule[];
	selectedMessageId: number | undefined;
	setSelectedMessageId: (rowId: number) => void;
}) {
	const [expandedMessageId, setExpandedMessageId] = useState<number | undefined>();

	Logger.debug('Rendering ScheduleTable', {
		component: 'ScheduleTable',
		data: {
			messageCount: messages.length,
			selectedMessageId,
			expandedMessageId,
		},
	});

	const handleRowClick = (messageId: number) => {
		Logger.debug('Message row clicked', {
			component: 'ScheduleTable',
			data: {
				messageId,
				previousSelection: selectedMessageId,
				previousExpanded: expandedMessageId,
			},
		});

		// Toggle expansion and selection
		if (expandedMessageId === messageId) {
			setExpandedMessageId(undefined);
			setSelectedMessageId(messageId);
		} else {
			setExpandedMessageId(messageId);
			setSelectedMessageId(messageId);
		}
	};

	const renderedMessages = messages.map((entry, _idx) => {
		const isExpanded = expandedMessageId === entry.id;
		const isSelected = selectedMessageId === entry.id;

		return (
			<React.Fragment key={entry.id}>
				<TableRow
					className={
						isSelected
							? 'hover:bg-zinc-50 dark:hover:bg-zinc-800 bg-zinc-100 dark:bg-zinc-800 cursor-pointer'
							: 'hover:bg-zinc-50 dark:hover:bg-zinc-800 cursor-pointer'
					}
					onClick={() => handleRowClick(entry.id)}
				>
					<TableCell className="w-8">
						{isExpanded ? (
							<ChevronDownIcon className="h-4 w-4 text-gray-500 dark:text-gray-400" />
						) : (
							<ChevronRightIcon className="h-4 w-4 text-gray-500 dark:text-gray-400" />
						)}
					</TableCell>
					<TableCell className="w-32">
						<StatusBadge status={entry.status} />
					</TableCell>
					<TableCell className="w-44">
						{entry.contact_detail
								? `${entry.contact_detail.first_name} ${entry.contact_detail.last_name}`
								: entry.group_detail
									? entry.group_detail.name
									: 'N/A'}
					</TableCell>
					<TableCell className="w-20">{dayjs(entry.scheduled_time).format('hh:mmA')} </TableCell>
					<TableCell className="w-20">{entry.sent_time ? dayjs(entry.sent_time).format('hh:mmA') : '-'}</TableCell>
					<TableCell className="w-32">
						{entry.phone
							? entry.phone.replace(/(\d{4})(\d{3})(\d{3})/, '$1 $2 $3')
							: entry.recipient_count
								? `${entry.recipient_count} recipients`
								: '-'}
					</TableCell>
					<TableCell className="w-16">{entry.format || 'SMS'}</TableCell>
					<TableCell className="w-16">{entry.message_parts}</TableCell>
					<TableCell> {entry.text && entry.text.length > 40 ? entry.text.substring(0, 40) + '...' : entry.text}</TableCell>
				</TableRow>
				{isExpanded && (
					<TableRow className="bg-zinc-100 dark:bg-zinc-800">
						<TableCell colSpan={9} className="p-0">
							<ScheduleDetails message={entry} />
						</TableCell>
					</TableRow>
				)}
			</React.Fragment>
		);
	});

	return (
		<Table>
			<TableHead>
				<TableRow>
					<TableHeader className="w-8"></TableHeader>
					<TableHeader>Status</TableHeader>
					<TableHeader>Name</TableHeader>
					<TableHeader className="w-20">Scheduled Time</TableHeader>
					<TableHeader className="w-20">Sent Time</TableHeader>
					<TableHeader className="w-32">Phone</TableHeader>
					<TableHeader className="w-16">Type</TableHeader>
					<TableHeader className="w-16">Msg Parts</TableHeader>
					<TableHeader>Message</TableHeader>
				</TableRow>
			</TableHead>
			<TableBody>{renderedMessages}</TableBody>
		</Table>
	);
}
