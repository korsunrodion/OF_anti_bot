import { Controller, Get, Param, ParseIntPipe, Query } from '@nestjs/common';
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
import {
  PaginationQueryDto,
  PaginatedResponseDto,
  SubscriberFilterDto,
} from './dto/pagination.dto';

const SUBSCRIPTION_EXAMPLE = {
  trackingLinkId: 12345,
  trackingLinkName: '@model_username',
  username: 'john_doe',
  userId: 987654,
  subscriptionDate: '2024-03-15T10:00:00.000Z',
  riskLevel: 'high',
  avatarUrl: 'https://example.com/avatar.jpg',
  header: 'https://example.com/header.jpg',
  isOnlineMatchesSubscription: true,
  isReadingMessages: true,
};

@ApiBearerAuth()
@ApiTags('tracking-links')
@Controller('tracking-links')
export class TrackingLinkResultsController {
  constructor(private readonly repository: TrackingLinkRepository) {}

  @ApiOperation({ summary: 'Get all subscriptions' })
  @ApiQuery({ name: 'page', required: false, example: 1 })
  @ApiQuery({ name: 'limit', required: false, example: 20 })
  @ApiQuery({
    name: 'createdSince',
    required: false,
    example: '2026-05-01T00:00:00.000Z',
  })
  @ApiQuery({
    name: 'updatedSince',
    required: false,
    example: '2026-05-01T00:00:00.000Z',
  })
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
      { createdSince: query.createdSince, updatedSince: query.updatedSince },
    );
    return { data, total, page: query.page, limit: query.limit };
  }

  @ApiOperation({ summary: 'Get summary for a tracking link' })
  @ApiParam({ name: 'trackingLinkId', example: 12345 })
  @ApiResponse({
    status: 200,
    type: TrackingLinkDto,
    content: {
      'application/json': {
        example: {
          trackingLinkId: 12345,
          trackingLinkName: '@model_username',
          riskLevel: 'high',
          count: 42,
        },
      },
    },
  })
  @ApiResponse({ status: 404, description: 'Tracking link not found' })
  @Get(':trackingLinkId/summary')
  async getSummary(
    @Param('trackingLinkId', ParseIntPipe) trackingLinkId: number,
  ): Promise<TrackingLinkDto> {
    return this.repository.findLinkSummary(trackingLinkId);
  }

  @ApiOperation({ summary: 'Get subscriptions for a tracking link' })
  @ApiParam({ name: 'trackingLinkId', example: 12345 })
  @ApiQuery({
    name: 'createdSince',
    required: false,
    example: '2026-05-01T00:00:00.000Z',
  })
  @ApiQuery({
    name: 'updatedSince',
    required: false,
    example: '2026-05-01T00:00:00.000Z',
  })
  @ApiResponse({
    status: 200,
    description: 'Paginated subscriptions',
    content: {
      'application/json': {
        example: {
          data: [SUBSCRIPTION_EXAMPLE],
          total: 50,
        },
      },
    },
  })
  @Get(':trackingLinkId')
  async findByLinkId(
    @Param('trackingLinkId', ParseIntPipe) trackingLinkId: number,
    @Query() query: SubscriberFilterDto,
  ): Promise<TrackingLinkSubscriptionDto[]> {
    return this.repository.findSubscriptionsByLinkId(trackingLinkId, {
      createdSince: query.createdSince,
      updatedSince: query.updatedSince,
    });
  }
}
