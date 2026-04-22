import { Controller, Get, Param, Query } from '@nestjs/common';
import {
  ApiBearerAuth,
  ApiOperation,
  ApiParam,
  ApiQuery,
  ApiResponse,
  ApiTags,
} from '@nestjs/swagger';
import { TrackingLinkRepository } from './repositories/tracking-link.repository';
import { TrackingLinkSubscriptionDto } from './dto/tracking-link-subscription.dto';
import { TrackingLinkDto } from './dto/tracking-link.dto';
import { PaginationQueryDto, PaginatedResponseDto } from './dto/pagination.dto';

const SUBSCRIPTION_EXAMPLE = {
  trackingLinkId: 'link_abc123',
  username: 'john_doe',
  userId: 987654,
  subscriptionDate: '2024-03-15T10:00:00.000Z',
  riskLevel: 'high',
};

@ApiBearerAuth()
@ApiTags('tracking-links')
@Controller('tracking-links')
export class TrackingLinkResultsController {
  constructor(private readonly repository: TrackingLinkRepository) {}

  @ApiOperation({ summary: 'Get all subscriptions' })
  @ApiQuery({ name: 'page', required: false, example: 1 })
  @ApiQuery({ name: 'limit', required: false, example: 20 })
  @ApiResponse({
    status: 200,
    description: 'Paginated subscriptions',
    content: {
      'application/json': {
        example: {
          data: [SUBSCRIPTION_EXAMPLE],
          total: 100,
          page: 1,
          limit: 20,
        },
      },
    },
  })
  @Get()
  async findAll(
    @Query() query: PaginationQueryDto,
  ): Promise<PaginatedResponseDto<TrackingLinkSubscriptionDto>> {
    const [data, total] = await this.repository.findAllSubscriptions(
      query.page,
      query.limit,
    );
    return { data, total, page: query.page, limit: query.limit };
  }

  @ApiOperation({ summary: 'Get summary for a tracking link' })
  @ApiParam({ name: 'trackingLinkId', example: 'link_abc123' })
  @ApiResponse({
    status: 200,
    type: TrackingLinkDto,
    content: {
      'application/json': {
        example: {
          trackingLinkId: 'link_abc123',
          riskLevel: 'high',
          count: 42,
        },
      },
    },
  })
  @ApiResponse({ status: 404, description: 'Tracking link not found' })
  @Get(':trackingLinkId/summary')
  async getSummary(
    @Param('trackingLinkId') trackingLinkId: string,
  ): Promise<TrackingLinkDto> {
    return this.repository.findLinkSummary(trackingLinkId);
  }

  @ApiOperation({ summary: 'Get subscriptions for a tracking link' })
  @ApiParam({ name: 'trackingLinkId', example: 'link_abc123' })
  @ApiQuery({ name: 'page', required: false, example: 1 })
  @ApiQuery({ name: 'limit', required: false, example: 20 })
  @ApiResponse({
    status: 200,
    description: 'Paginated subscriptions',
    content: {
      'application/json': {
        example: {
          data: [SUBSCRIPTION_EXAMPLE],
          total: 50,
          page: 1,
          limit: 20,
        },
      },
    },
  })
  @Get(':trackingLinkId')
  async findByLinkId(
    @Param('trackingLinkId') trackingLinkId: string,
    @Query() query: PaginationQueryDto,
  ): Promise<PaginatedResponseDto<TrackingLinkSubscriptionDto>> {
    const [data, total] = await this.repository.findSubscriptionsByLinkId(
      trackingLinkId,
      query.page,
      query.limit,
    );
    return { data, total, page: query.page, limit: query.limit };
  }
}
