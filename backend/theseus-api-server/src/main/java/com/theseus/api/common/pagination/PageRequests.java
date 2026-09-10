package com.theseus.api.common.pagination;

import org.springframework.data.domain.PageRequest;

public final class PageRequests {

	private PageRequests() {}

	public static PageRequest create(int page, int size) {
		return PageRequest.of(Math.max(page, 0), Math.max(size, 1));
	}
}
