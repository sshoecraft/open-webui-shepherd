<script lang="ts">
	import { WEBUI_BASE_URL, WEBUI_API_BASE_URL } from '$lib/constants';
	import { config } from '$lib/stores';

	export let className = 'size-8';
	export let src = `${WEBUI_BASE_URL}/static/favicon.png`;

	$: defaultLogo = $config?.custom_logo ? `${WEBUI_API_BASE_URL}/configs/branding/logo` : `${WEBUI_BASE_URL}/static/favicon.png`;
	$: isDefaultLogo = src === '' || src === `${WEBUI_BASE_URL}/static/favicon.png`;
	// Model profile images from API will show custom logo if configured, so don't round those either
	$: isModelProfileImage = src.includes('/models/model/profile/image');
	$: useRoundedStyle = $config?.custom_logo ? (!isDefaultLogo && !isModelProfileImage) : true;
</script>

<img
	aria-hidden="true"
	src={isDefaultLogo
		? defaultLogo
		: src.startsWith(WEBUI_BASE_URL) ||
			  src.startsWith(WEBUI_API_BASE_URL) ||
			  src.startsWith('https://www.gravatar.com/avatar/') ||
			  src.startsWith('data:') ||
			  src.startsWith('/')
			? src
			: `${WEBUI_BASE_URL}/user.png`}
	class=" {className} object-cover {useRoundedStyle ? 'rounded-full' : ''}"
	alt="profile"
	draggable="false"
/>
