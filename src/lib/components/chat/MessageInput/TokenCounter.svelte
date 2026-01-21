<script lang="ts">
	import { getContext } from 'svelte';
	import { models } from '$lib/stores';
	import { createMessagesList } from '$lib/utils';
	import Tooltip from '$lib/components/common/Tooltip.svelte';

	const i18n = getContext('i18n');

	export let history;
	export let selectedModelIds: string[] = [];

	// Calculate used tokens from the latest assistant message's usage
	$: usedTokens = calculateUsedTokens(history);

	// Get max context from the first selected model (primary model)
	$: maxTokens = getMaxContext(selectedModelIds[0]);

	// Display string
	$: tokenDisplay =
		maxTokens > 0
			? `${formatNumber(usedTokens)} / ${formatNumber(maxTokens)}`
			: `${formatNumber(usedTokens)}`;

	// Usage percentage for visual indicator
	$: usagePercent = maxTokens > 0 ? Math.min((usedTokens / maxTokens) * 100, 100) : 0;

	// Color coding based on usage
	$: colorClass =
		usagePercent > 90
			? 'text-red-500 dark:text-red-400'
			: usagePercent > 75
				? 'text-yellow-500 dark:text-yellow-400'
				: 'text-gray-500 dark:text-gray-400';

	function calculateUsedTokens(hist): number {
		if (!hist?.currentId || !hist?.messages) return 0;

		// Get the message list in order
		const messages = createMessagesList(hist, hist.currentId);

		// Find the latest assistant message with usage data
		for (let i = messages.length - 1; i >= 0; i--) {
			const msg = messages[i];
			if (msg.role === 'assistant' && msg.usage) {
				// prompt_tokens from assistant represents all input tokens
				// Add completion_tokens to get total context used
				const prompt = msg.usage.prompt_tokens || 0;
				const completion = msg.usage.completion_tokens || 0;
				return prompt + completion;
			}
		}

		return 0;
	}

	function getMaxContext(modelId: string): number {
		if (!modelId) return 0;
		const model = $models.find((m) => m.id === modelId);

		// Check various locations for context length:
		// - vLLM/Shepherd: max_model_len at top level
		// - Ollama: num_ctx in params
		// - OpenAI-style: max_tokens or context_length in params/meta
		return (
			(model as any)?.max_model_len ||
			model?.info?.params?.num_ctx ||
			model?.info?.params?.max_tokens ||
			model?.info?.meta?.context_length ||
			0
		);
	}

	function formatNumber(num: number): string {
		// Use binary units (1024) since token counts follow computing conventions
		if (num >= 1048576) return `${(num / 1048576).toFixed(1)}M`;
		if (num >= 1024) return `${(num / 1024).toFixed(1)}K`;
		return num.toString();
	}
</script>

{#if usedTokens > 0 || maxTokens > 0}
	<Tooltip
		content={maxTokens > 0
			? $i18n.t('Context: {{used}} / {{max}} tokens ({{percent}}%)', {
					used: usedTokens.toLocaleString(),
					max: maxTokens.toLocaleString(),
					percent: usagePercent.toFixed(1)
				})
			: $i18n.t('Tokens used: {{used}}', { used: usedTokens.toLocaleString() })}
		placement="top"
	>
		<div
			class="flex items-center gap-1 px-1.5 py-0.5 text-xs font-mono rounded
				   bg-transparent hover:bg-gray-100 dark:hover:bg-gray-800
				   {colorClass} transition cursor-default"
		>
			<svg
				xmlns="http://www.w3.org/2000/svg"
				viewBox="0 0 20 20"
				fill="currentColor"
				class="size-3.5"
			>
				<path
					fill-rule="evenodd"
					d="M10 18a8 8 0 100-16 8 8 0 000 16zm.75-13a.75.75 0 00-1.5 0v5c0 .414.336.75.75.75h4a.75.75 0 000-1.5h-3.25V5z"
					clip-rule="evenodd"
				/>
			</svg>
			<span>{tokenDisplay}</span>
		</div>
	</Tooltip>
{/if}
