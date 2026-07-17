// Logger utility for consistent logging across the frontend

type LogLevel = 'debug' | 'info' | 'warn' | 'error';

interface LogOptions {
	component?: string;
	data?: unknown;
}

class Logger {
	private static currentLevel: LogLevel = (import.meta.env.VITE_LOG_LEVEL as LogLevel) || 'info';

	private static formatMessage(level: LogLevel, message: string, options?: LogOptions): string {
		const timestamp = new Date().toLocaleString();
		const component = options?.component ? `[${options.component}]` : '';
		return `${timestamp} ${level.toUpperCase()} ${component} ${message}`;
	}

	static debug(message: string, options?: LogOptions): void {
		if (this.currentLevel === 'debug') {
			console.debug(this.formatMessage('debug', message, options), options?.data || '');
		}
	}

	static info(message: string, options?: LogOptions): void {
		console.info(this.formatMessage('info', message, options), options?.data || '');
	}

	static warn(message: string, options?: LogOptions): void {
		console.warn(this.formatMessage('warn', message, options), options?.data || '');
	}

	static error(message: string, options?: LogOptions): void {
		console.error(this.formatMessage('error', message, options), options?.data || '');
	}
}

export default Logger;
