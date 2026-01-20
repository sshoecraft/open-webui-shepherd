<script lang="ts">
	import fileSaver from 'file-saver';
	const { saveAs } = fileSaver;

	import { v4 as uuidv4 } from 'uuid';
	import { toast } from 'svelte-sonner';

	import { getBackendConfig, getModels, getTaskConfig, updateTaskConfig } from '$lib/apis';
	import { setDefaultPromptSuggestions, getModelsConfig, setModelsConfig } from '$lib/apis/configs';
	import { config, settings, user, WEBUI_NAME } from '$lib/stores';
	import { createEventDispatcher, onMount, getContext } from 'svelte';

	import { banners as _banners } from '$lib/stores';
	import type { Banner } from '$lib/types';

	import { getBaseModels } from '$lib/apis/models';
	import { getBanners, setBanners, getBrandingConfig, setBrandingConfig, uploadBrandingLogo, deleteBrandingLogo } from '$lib/apis/configs';
	import { WEBUI_API_BASE_URL } from '$lib/constants';
	import { verifyOpenAIConnection } from '$lib/apis/openai';

	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import ArrowPath from '$lib/components/icons/ArrowPath.svelte';
	import Banners from './Interface/Banners.svelte';
	import PromptSuggestions from '$lib/components/workspace/Models/PromptSuggestions.svelte';

	const dispatch = createEventDispatcher();

	const i18n = getContext('i18n');

	let taskModelUrlStatus = null; // null = not tested, true = success, false = failed
	let taskModelUrlTesting = false;

	const testTaskModelUrl = async () => {
		if (!taskConfig.TASK_MODEL_URL) {
			toast.error($i18n.t('Please enter a URL first'));
			return;
		}

		taskModelUrlTesting = true;
		taskModelUrlStatus = null;

		try {
			const url = taskConfig.TASK_MODEL_URL.replace(/\/$/, '');
			const res = await verifyOpenAIConnection(
				localStorage.token,
				{ url, key: '', config: {} },
				false
			);

			if (res) {
				taskModelUrlStatus = true;
				toast.success($i18n.t('Server connection verified'));
			} else {
				taskModelUrlStatus = false;
			}
		} catch (error) {
			taskModelUrlStatus = false;
			toast.error(`${error}`);
		} finally {
			taskModelUrlTesting = false;
		}
	};

	let taskConfig = {
		TASK_MODEL: '',
		TASK_MODEL_EXTERNAL: '',
		TASK_MODEL_URL: '',
		ENABLE_TITLE_GENERATION: true,
		TITLE_GENERATION_PROMPT_TEMPLATE: '',
		ENABLE_FOLLOW_UP_GENERATION: true,
		FOLLOW_UP_GENERATION_PROMPT_TEMPLATE: '',
		IMAGE_PROMPT_GENERATION_PROMPT_TEMPLATE: '',
		ENABLE_AUTOCOMPLETE_GENERATION: true,
		AUTOCOMPLETE_GENERATION_INPUT_MAX_LENGTH: -1,
		TAGS_GENERATION_PROMPT_TEMPLATE: '',
		ENABLE_TAGS_GENERATION: true,
		ENABLE_SEARCH_QUERY_GENERATION: true,
		ENABLE_RETRIEVAL_QUERY_GENERATION: true,
		QUERY_GENERATION_PROMPT_TEMPLATE: '',
		TOOLS_FUNCTION_CALLING_PROMPT_TEMPLATE: '',
		VOICE_MODE_PROMPT_TEMPLATE: ''
	};

	let promptSuggestions = [];
	let banners: Banner[] = [];
	let enableIntegrationsMenu = true;
	let enableChatControls = true;
	let enableTemporaryChat = true;

	// Branding
	let customName = '';
	let customLogo = '';
	let enableSplashScreen = true;
	let logoFileInput: HTMLInputElement;

	const handleLogoUpload = async (event: Event) => {
		const target = event.target as HTMLInputElement;
		const file = target.files?.[0];
		if (!file) return;

		try {
			const result = await uploadBrandingLogo(localStorage.token, file);
			if (result) {
				customLogo = result.CUSTOM_LOGO;
				toast.success($i18n.t('Logo uploaded successfully'));
			}
		} catch (error) {
			toast.error($i18n.t('Failed to upload logo'));
		}
	};

	const handleLogoDelete = async () => {
		try {
			await deleteBrandingLogo(localStorage.token);
			customLogo = '';
			toast.success($i18n.t('Logo deleted successfully'));
		} catch (error) {
			toast.error($i18n.t('Failed to delete logo'));
		}
	};

	const updateInterfaceHandler = async () => {
		taskConfig = await updateTaskConfig(localStorage.token, taskConfig);

		promptSuggestions = promptSuggestions.filter((p) => p.content !== '');
		promptSuggestions = await setDefaultPromptSuggestions(localStorage.token, promptSuggestions);
		await updateBanners();

		await setModelsConfig(localStorage.token, {
			ENABLE_INTEGRATIONS_MENU: enableIntegrationsMenu,
			ENABLE_CHAT_CONTROLS: enableChatControls,
			ENABLE_TEMPORARY_CHAT: enableTemporaryChat
		});

		// Save branding config
		await setBrandingConfig(localStorage.token, {
			CUSTOM_NAME: customName,
			CUSTOM_LOGO: customLogo,
			ENABLE_SPLASH_SCREEN: enableSplashScreen
		});
		// Cache splash screen setting for instant effect on page load
		localStorage.setItem('enableSplashScreen', enableSplashScreen ? 'true' : 'false');

		const backendConfig = await getBackendConfig();
		await config.set(backendConfig);
		// Update the WEBUI_NAME store so sidebar updates immediately
		await WEBUI_NAME.set(backendConfig.name);
	};

	const updateBanners = async () => {
		_banners.set(await setBanners(localStorage.token, banners));
	};

	let workspaceModels = null;
	let baseModels = null;

	let models = null;

	const init = async () => {
		taskConfig = await getTaskConfig(localStorage.token);
		promptSuggestions = $config?.default_prompt_suggestions ?? [];
		banners = await getBanners(localStorage.token);

		const modelsConfig = await getModelsConfig(localStorage.token);
		enableIntegrationsMenu = modelsConfig?.ENABLE_INTEGRATIONS_MENU ?? true;
		enableChatControls = modelsConfig?.ENABLE_CHAT_CONTROLS ?? true;
		enableTemporaryChat = modelsConfig?.ENABLE_TEMPORARY_CHAT ?? true;

		// Load branding config
		const brandingConfig = await getBrandingConfig(localStorage.token);
		customName = brandingConfig?.CUSTOM_NAME ?? '';
		customLogo = brandingConfig?.CUSTOM_LOGO ?? '';
		enableSplashScreen = brandingConfig?.ENABLE_SPLASH_SCREEN ?? true;

		workspaceModels = await getBaseModels(localStorage.token);
		baseModels = await getModels(localStorage.token, null, false);

		models = baseModels.map((m) => {
			const workspaceModel = workspaceModels.find((wm) => wm.id === m.id);

			if (workspaceModel) {
				return {
					...m,
					...workspaceModel
				};
			} else {
				return {
					...m,
					id: m.id,
					name: m.name,

					is_active: true
				};
			}
		});

		console.debug('models', models);
	};

	onMount(async () => {
		await init();
	});
</script>

{#if models !== null && taskConfig}
	<form
		class="flex flex-col h-full justify-between space-y-3 text-sm"
		on:submit|preventDefault={() => {
			updateInterfaceHandler();
			dispatch('save');
		}}
	>
		<div class="  overflow-y-scroll scrollbar-hidden h-full pr-1.5">
			<div class="mb-3.5">
				<div class=" mt-0.5 mb-2.5 text-base font-medium">{$i18n.t('Tasks')}</div>

				<hr class=" border-gray-100/30 dark:border-gray-850/30 my-2" />

				<div class=" mb-2 font-medium flex items-center">
					<div class=" text-xs mr-1">{$i18n.t('Task Model')}</div>
					<Tooltip
						content={$i18n.t(
							'A task model is used when performing tasks such as generating titles for chats and web search queries'
						)}
					>
						<svg
							xmlns="http://www.w3.org/2000/svg"
							fill="none"
							viewBox="0 0 24 24"
							stroke-width="1.5"
							stroke="currentColor"
							class="size-3.5"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								d="m11.25 11.25.041-.02a.75.75 0 0 1 1.063.852l-.708 2.836a.75.75 0 0 0 1.063.853l.041-.021M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9-3.75h.008v.008H12V8.25Z"
							/>
						</svg>
					</Tooltip>
				</div>

				<div class=" mb-2.5 flex w-full gap-2">
					<div class="flex-1">
						<div class=" text-xs mb-1">{$i18n.t('Local Task Model')}</div>
						<select
							class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
							bind:value={taskConfig.TASK_MODEL}
							placeholder={$i18n.t('Select a model')}
							on:change={() => {
								if (taskConfig.TASK_MODEL) {
									const model = models.find((m) => m.id === taskConfig.TASK_MODEL);
									if (model) {
										if (model?.access_control !== null) {
											toast.error(
												$i18n.t(
													'This model is not publicly available. Please select another model.'
												)
											);
										}

										taskConfig.TASK_MODEL = model.id;
									} else {
										taskConfig.TASK_MODEL = '';
									}
								}
							}}
						>
							<option value="" selected>{$i18n.t('Current Model')}</option>
							{#each models as model}
								<option value={model.id} class="bg-gray-100 dark:bg-gray-700">
									{model.name}
									{model?.connection_type === 'local' ? `(${$i18n.t('Local')})` : ''}
								</option>
							{/each}
						</select>
					</div>

					<div class="flex-1">
						<div class=" text-xs mb-1">{$i18n.t('External Task Model')}</div>
						<select
							class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
							bind:value={taskConfig.TASK_MODEL_EXTERNAL}
							placeholder={$i18n.t('Select a model')}
							on:change={() => {
								if (taskConfig.TASK_MODEL_EXTERNAL) {
									const model = models.find((m) => m.id === taskConfig.TASK_MODEL_EXTERNAL);
									if (model) {
										if (model?.access_control !== null) {
											toast.error(
												$i18n.t(
													'This model is not publicly available. Please select another model.'
												)
											);
										}

										taskConfig.TASK_MODEL_EXTERNAL = model.id;
									} else {
										taskConfig.TASK_MODEL_EXTERNAL = '';
									}
								}
							}}
						>
							<option value="" selected>{$i18n.t('Current Model')}</option>
							{#each models as model}
								<option value={model.id} class="bg-gray-100 dark:bg-gray-700">
									{model.name}
									{model?.connection_type === 'local' ? `(${$i18n.t('Local')})` : ''}
								</option>
							{/each}
						</select>
					</div>
				</div>

				<div class="mb-2.5">
					<div class=" text-xs mb-1">{$i18n.t('Task Model URL (Direct)')}</div>
					<div class="flex gap-2 items-center">
						<input
							class="flex-1 rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
							type="text"
							placeholder="http://localhost:8001/v1"
							bind:value={taskConfig.TASK_MODEL_URL}
						/>
						<Tooltip content={$i18n.t('Verify Connection')}>
							<button
								class="p-2 rounded-lg bg-gray-50 dark:bg-gray-850 hover:bg-gray-100 dark:hover:bg-gray-800 transition {taskModelUrlStatus === true ? 'text-green-500' : taskModelUrlStatus === false ? 'text-red-500' : ''}"
								type="button"
								on:click={testTaskModelUrl}
								disabled={taskModelUrlTesting}
								aria-label={$i18n.t('Verify Connection')}
							>
								{#if taskModelUrlTesting}
									<Spinner className="size-4" />
								{:else}
									<ArrowPath className="size-4" />
								{/if}
							</button>
						</Tooltip>
					</div>
					<div class="text-xs text-gray-500 mt-1">
						{$i18n.t('Optional: Direct URL to an OpenAI-compatible endpoint for tasks. Bypasses model list.')}
					</div>
				</div>

				<div class="mb-2.5 flex w-full items-center justify-between">
					<div class=" self-center text-xs font-medium">
						{$i18n.t('Title Generation')}
					</div>

					<Switch bind:state={taskConfig.ENABLE_TITLE_GENERATION} />
				</div>

				{#if taskConfig.ENABLE_TITLE_GENERATION}
					<div class="mb-2.5">
						<div class=" mb-1 text-xs font-medium">{$i18n.t('Title Generation Prompt')}</div>

						<Tooltip
							content={$i18n.t('Leave empty to use the default prompt, or enter a custom prompt')}
							placement="top-start"
						>
							<Textarea
								bind:value={taskConfig.TITLE_GENERATION_PROMPT_TEMPLATE}
								placeholder={$i18n.t(
									'Leave empty to use the default prompt, or enter a custom prompt'
								)}
							/>
						</Tooltip>
					</div>
				{/if}

				<div class="mb-2.5 flex w-full items-center justify-between">
					<div class=" self-center text-xs font-medium">
						{$i18n.t('Voice Mode Custom Prompt')}
					</div>

					<Switch
						state={taskConfig.VOICE_MODE_PROMPT_TEMPLATE != null}
						on:change={(e) => {
							if (e.detail) {
								taskConfig.VOICE_MODE_PROMPT_TEMPLATE = '';
							} else {
								taskConfig.VOICE_MODE_PROMPT_TEMPLATE = null;
							}
						}}
					/>
				</div>

				{#if taskConfig.VOICE_MODE_PROMPT_TEMPLATE != null}
					<div class="mb-2.5">
						<div class=" mb-1 text-xs font-medium">{$i18n.t('Voice Mode Prompt')}</div>

						<Tooltip
							content={$i18n.t('Leave empty to use the default prompt, or enter a custom prompt')}
							placement="top-start"
						>
							<Textarea
								bind:value={taskConfig.VOICE_MODE_PROMPT_TEMPLATE}
								placeholder={$i18n.t(
									'Leave empty to use the default prompt, or enter a custom prompt'
								)}
							/>
						</Tooltip>
					</div>
				{/if}

				<div class="mb-2.5 flex w-full items-center justify-between">
					<div class=" self-center text-xs font-medium">
						{$i18n.t('Follow Up Generation')}
					</div>

					<Switch bind:state={taskConfig.ENABLE_FOLLOW_UP_GENERATION} />
				</div>

				{#if taskConfig.ENABLE_FOLLOW_UP_GENERATION}
					<div class="mb-2.5">
						<div class=" mb-1 text-xs font-medium">{$i18n.t('Follow Up Generation Prompt')}</div>

						<Tooltip
							content={$i18n.t('Leave empty to use the default prompt, or enter a custom prompt')}
							placement="top-start"
						>
							<Textarea
								bind:value={taskConfig.FOLLOW_UP_GENERATION_PROMPT_TEMPLATE}
								placeholder={$i18n.t(
									'Leave empty to use the default prompt, or enter a custom prompt'
								)}
							/>
						</Tooltip>
					</div>
				{/if}

				<div class="mb-2.5 flex w-full items-center justify-between">
					<div class=" self-center text-xs font-medium">
						{$i18n.t('Tags Generation')}
					</div>

					<Switch bind:state={taskConfig.ENABLE_TAGS_GENERATION} />
				</div>

				{#if taskConfig.ENABLE_TAGS_GENERATION}
					<div class="mb-2.5">
						<div class=" mb-1 text-xs font-medium">{$i18n.t('Tags Generation Prompt')}</div>

						<Tooltip
							content={$i18n.t('Leave empty to use the default prompt, or enter a custom prompt')}
							placement="top-start"
						>
							<Textarea
								bind:value={taskConfig.TAGS_GENERATION_PROMPT_TEMPLATE}
								placeholder={$i18n.t(
									'Leave empty to use the default prompt, or enter a custom prompt'
								)}
							/>
						</Tooltip>
					</div>
				{/if}

				<div class="mb-2.5 flex w-full items-center justify-between">
					<div class=" self-center text-xs font-medium">
						{$i18n.t('Retrieval Query Generation')}
					</div>

					<Switch bind:state={taskConfig.ENABLE_RETRIEVAL_QUERY_GENERATION} />
				</div>

				<div class="mb-2.5 flex w-full items-center justify-between">
					<div class=" self-center text-xs font-medium">
						{$i18n.t('Web Search Query Generation')}
					</div>

					<Switch bind:state={taskConfig.ENABLE_SEARCH_QUERY_GENERATION} />
				</div>

				<div class="mb-2.5">
					<div class=" mb-1 text-xs font-medium">{$i18n.t('Query Generation Prompt')}</div>

					<Tooltip
						content={$i18n.t('Leave empty to use the default prompt, or enter a custom prompt')}
						placement="top-start"
					>
						<Textarea
							bind:value={taskConfig.QUERY_GENERATION_PROMPT_TEMPLATE}
							placeholder={$i18n.t(
								'Leave empty to use the default prompt, or enter a custom prompt'
							)}
						/>
					</Tooltip>
				</div>

				<div class="mb-2.5 flex w-full items-center justify-between">
					<div class=" self-center text-xs font-medium">
						{$i18n.t('Autocomplete Generation')}
					</div>

					<Tooltip content={$i18n.t('Enable autocomplete generation for chat messages')}>
						<Switch bind:state={taskConfig.ENABLE_AUTOCOMPLETE_GENERATION} />
					</Tooltip>
				</div>

				{#if taskConfig.ENABLE_AUTOCOMPLETE_GENERATION}
					<div class="mb-2.5">
						<div class=" mb-1 text-xs font-medium">
							{$i18n.t('Autocomplete Generation Input Max Length')}
						</div>

						<Tooltip
							content={$i18n.t('Character limit for autocomplete generation input')}
							placement="top-start"
						>
							<input
								class="w-full outline-hidden bg-transparent"
								bind:value={taskConfig.AUTOCOMPLETE_GENERATION_INPUT_MAX_LENGTH}
								placeholder={$i18n.t('-1 for no limit, or a positive integer for a specific limit')}
							/>
						</Tooltip>
					</div>
				{/if}

				<div class="mb-2.5">
					<div class=" mb-1 text-xs font-medium">{$i18n.t('Image Prompt Generation Prompt')}</div>

					<Tooltip
						content={$i18n.t('Leave empty to use the default prompt, or enter a custom prompt')}
						placement="top-start"
					>
						<Textarea
							bind:value={taskConfig.IMAGE_PROMPT_GENERATION_PROMPT_TEMPLATE}
							placeholder={$i18n.t(
								'Leave empty to use the default prompt, or enter a custom prompt'
							)}
						/>
					</Tooltip>
				</div>

				<div class="mb-2.5">
					<div class=" mb-1 text-xs font-medium">{$i18n.t('Tools Function Calling Prompt')}</div>

					<Tooltip
						content={$i18n.t('Leave empty to use the default prompt, or enter a custom prompt')}
						placement="top-start"
					>
						<Textarea
							bind:value={taskConfig.TOOLS_FUNCTION_CALLING_PROMPT_TEMPLATE}
							placeholder={$i18n.t(
								'Leave empty to use the default prompt, or enter a custom prompt'
							)}
						/>
					</Tooltip>
				</div>
			</div>

			<div class="mb-3.5">
				<div class=" mt-0.5 mb-2.5 text-base font-medium">{$i18n.t('Chat')}</div>

				<hr class=" border-gray-100/30 dark:border-gray-850/30 my-2" />

				<div class="mb-2.5 flex w-full items-center justify-between">
					<div class="self-center text-xs font-medium">
						{$i18n.t('Show Integrations Menu')}
					</div>

					<Switch bind:state={enableIntegrationsMenu} />
				</div>

				<div class="mb-2.5 flex w-full items-center justify-between">
					<div class="self-center text-xs font-medium">
						{$i18n.t('Show Chat Controls')}
					</div>

					<Switch bind:state={enableChatControls} />
				</div>

				<div class="mb-2.5 flex w-full items-center justify-between">
					<div class="self-center text-xs font-medium">
						{$i18n.t('Show Temporary Chat')}
					</div>

					<Switch bind:state={enableTemporaryChat} />
				</div>
			</div>

			<div class="mb-3.5">
				<div class=" mt-0.5 mb-2.5 text-base font-medium">{$i18n.t('UI')}</div>

				<hr class=" border-gray-100/30 dark:border-gray-850/30 my-2" />

				<div class="mb-2.5">
					<div class="flex w-full justify-between">
						<div class=" self-center text-xs">
							{$i18n.t('Banners')}
						</div>

						<button
							class="p-1 px-3 text-xs flex rounded-sm transition"
							type="button"
							on:click={() => {
								if (banners.length === 0 || banners.at(-1).content !== '') {
									banners = [
										...banners,
										{
											id: uuidv4(),
											type: '',
											title: '',
											content: '',
											dismissible: true,
											timestamp: Math.floor(Date.now() / 1000)
										}
									];
								}
							}}
						>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								viewBox="0 0 20 20"
								fill="currentColor"
								class="w-4 h-4"
							>
								<path
									d="M10.75 4.75a.75.75 0 00-1.5 0v4.5h-4.5a.75.75 0 000 1.5h4.5v4.5a.75.75 0 001.5 0v-4.5h4.5a.75.75 0 000-1.5h-4.5v-4.5z"
								/>
							</svg>
						</button>
					</div>

					<Banners bind:banners />
				</div>

				{#if $user?.role === 'admin'}
					<PromptSuggestions bind:promptSuggestions />

					{#if promptSuggestions.length > 0}
						<div class="text-xs text-left w-full mt-2">
							{$i18n.t('Adjusting these settings will apply changes universally to all users.')}
						</div>
					{/if}
				{/if}
			</div>

			<div class="mb-3.5">
				<div class=" mt-0.5 mb-2.5 text-base font-medium">{$i18n.t('Branding')}</div>

				<hr class=" border-gray-100/30 dark:border-gray-850/30 my-2" />

				<div class="mb-2.5">
					<div class=" self-center text-xs mb-1">{$i18n.t('Application Name')}</div>
					<Tooltip content={$i18n.t('Leave empty to use default name')} placement="top-start">
						<input
							class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
							type="text"
							placeholder={$i18n.t('Open WebUI')}
							bind:value={customName}
						/>
					</Tooltip>
				</div>

				<div class="mb-2.5">
					<div class=" self-center text-xs mb-1">{$i18n.t('Logo')}</div>
					<div class="flex items-center gap-3">
						{#if customLogo}
							<img
								src={`${WEBUI_API_BASE_URL}/configs/branding/logo?t=${Date.now()}`}
								alt="Custom Logo"
								class="w-12 h-12 object-contain rounded border border-gray-200 dark:border-gray-700"
							/>
							<button
								class="px-3 py-1.5 text-xs font-medium bg-red-500 hover:bg-red-600 text-white transition rounded-lg"
								type="button"
								on:click={handleLogoDelete}
							>
								{$i18n.t('Delete')}
							</button>
						{:else}
							<div class="w-12 h-12 rounded border border-dashed border-gray-300 dark:border-gray-600 flex items-center justify-center text-gray-400">
								<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-6 h-6">
									<path stroke-linecap="round" stroke-linejoin="round" d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909m-18 3.75h16.5a1.5 1.5 0 001.5-1.5V6a1.5 1.5 0 00-1.5-1.5H3.75A1.5 1.5 0 002.25 6v12a1.5 1.5 0 001.5 1.5zm10.5-11.25h.008v.008h-.008V8.25zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0z" />
								</svg>
							</div>
						{/if}
						<input
							type="file"
							accept="image/png,image/jpeg,image/svg+xml,image/webp"
							class="hidden"
							bind:this={logoFileInput}
							on:change={handleLogoUpload}
						/>
						<button
							class="px-3 py-1.5 text-xs font-medium bg-gray-100 hover:bg-gray-200 dark:bg-gray-800 dark:hover:bg-gray-700 transition rounded-lg"
							type="button"
							on:click={() => logoFileInput.click()}
						>
							{$i18n.t('Upload Logo')}
						</button>
					</div>
					<div class="text-xs text-gray-500 mt-1">
						{$i18n.t('Recommended size: 44x44 pixels. Supports PNG, JPEG, SVG, WebP.')}
					</div>
				</div>

				<div class="mb-2.5">
					<div class="flex justify-between items-center">
						<div class=" self-center text-xs">{$i18n.t('Enable Splash Screen')}</div>
						<Switch bind:state={enableSplashScreen} />
					</div>
					<div class="text-xs text-gray-500 mt-1">
						{$i18n.t('Show loading splash screen on page load')}
					</div>
				</div>
			</div>
		</div>

		<div class="flex justify-end text-sm font-medium">
			<button
				class="px-3.5 py-1.5 text-sm font-medium bg-black hover:bg-gray-900 text-white dark:bg-white dark:text-black dark:hover:bg-gray-100 transition rounded-full"
				type="submit"
			>
				{$i18n.t('Save')}
			</button>
		</div>
	</form>
{:else}
	<div class=" h-full w-full flex justify-center items-center">
		<Spinner className="size-5" />
	</div>
{/if}
