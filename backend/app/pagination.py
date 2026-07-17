import math

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class StandardPagination(PageNumberPagination):
    """This matches the v1 Express API pagination format"""
    page_size = 50
    page_size_query_param = 'limit'
    max_page_size = 50

    def get_paginated_response(self, data):
        total = self.page.paginator.count
        limit = self.get_page_size(self.request)
        total_pages = math.ceil(total / limit) if limit else 1

        return Response({
            'results': data,
            'pagination': {
                'total': total,
                'page': self.page.number,
                'limit': limit,
                'totalPages': total_pages,
                'hasNext': self.page.has_next(),
                'hasPrev': self.page.has_previous(),
            },
        })
